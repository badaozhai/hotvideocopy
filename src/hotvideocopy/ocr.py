"""硬字幕 / 花字 OCR（RapidOCR，onnxruntime 本地跑，不联网）。

工具只给「什么时刻、画面哪个高度、出现了什么字」，并把连续相同的文本合并成时间段。
「这是标题花字还是对白字幕」这类判断留给 Claude——y 值（0=顶 1=底）就是判断依据。

采样策略：默认读 shots.json 的镜头表，每镜按 sample_step 秒采样；没有 shots.json
就整片等间隔。字幕通常 ≥1s 一条，sample_step=0.8 基本不漏。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from .shots import frame_files
from .workspace import project_of, read_json, resolve_video, sub, write_json

_ENGINE: list = []  # 进程内单例：模型加载要几秒


def _engine():
    if not _ENGINE:
        from rapidocr_onnxruntime import RapidOCR
        _ENGINE.append(RapidOCR())
    return _ENGINE[0]


def _norm(text: str) -> str:
    return "".join(str(text or "").split())


def _ocr_one(img: Path) -> list[dict]:
    """单帧 OCR，返回 [{text, score, y, x}]，y/x 是框中心的归一化坐标（0=左/顶，1=右/底）。"""
    from PIL import Image
    with Image.open(img) as im:
        w, h = im.size
    result, _ = _engine()(str(img))
    if not result:
        return []
    out = []
    for box, text, score in result:
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        out.append({"text": str(text).strip(), "score": round(float(score), 3),
                    "x": round(sum(xs) / len(xs) / w, 3), "y": round(sum(ys) / len(ys) / h, 3)})
    return out


def _sample_points(dur: float, shots: list[dict] | None, step: float) -> list[float]:
    if shots:
        ts: list[float] = []
        for s in shots:
            st, en = s["t"]
            t = st + 0.15
            while t < en:
                ts.append(round(t, 3))
                t += step
        return ts
    return [round(t, 3) for t in _frange(0.15, dur, step)]


def _frange(start: float, stop: float, step: float) -> list[float]:
    out, t = [], start
    while t < stop:
        out.append(t)
        t += step
    return out


async def ocr_burned_text(video: str, sample_step: float = 0.8,
                          min_score: float = 0.65, max_width: int = 1080) -> dict:
    path = resolve_video(video)
    pid = project_of(path) or "scratch"

    from .media import duration_of
    dur = await duration_of(path)
    if not dur:
        raise RuntimeError("读不到视频时长，文件可能损坏")

    shots_data = read_json(sub(pid, "shots.json", create=False), {}) if pid != "scratch" else {}
    ts_list = _sample_points(dur, (shots_data or {}).get("shots"), sample_step)

    frames = await frame_files(video, ts_list, max_width)

    # OCR 是纯 CPU 串行活，丢一个线程按序跑，别开多线程打架（引擎非线程安全）
    def run_all() -> list[tuple[float, list[dict]]]:
        out = []
        for ts, img in frames:
            hits = [x for x in _ocr_one(img) if x["score"] >= min_score and x["text"]]
            out.append((ts, hits))
        return out

    per_frame = await asyncio.to_thread(run_all)

    # 连续相同文本合并成时间段：同一条字幕在相邻采样点反复出现，只留一个 span
    spans: list[dict] = []
    open_spans: dict[str, dict] = {}
    for ts, hits in sorted(per_frame, key=lambda x: x[0]):
        seen = set()
        for x in hits:
            key = _norm(x["text"])
            if not key or key in seen:
                continue
            seen.add(key)
            sp = open_spans.get(key)
            if sp and ts - sp["t"][1] <= sample_step * 1.8:
                sp["t"][1] = ts
                sp["hits"] += 1
                sp["score"] = max(sp["score"], x["score"])
            else:
                sp = {"text": x["text"], "t": [ts, ts], "y": x["y"], "x": x["x"],
                      "score": x["score"], "hits": 1}
                open_spans[key] = sp
                spans.append(sp)
    spans.sort(key=lambda s: s["t"][0])

    result = {
        "video": str(path),
        "project_id": pid,
        "engine": "rapidocr-onnxruntime",
        "sampled_frames": len(frames),
        "sample_step": sample_step,
        "spans": spans,
    }
    if pid != "scratch":
        result["file"] = write_json(sub(pid, "ocr.json"), result)
    return result

"""镜头分割与抽帧。

scene_split 只给切点，不判断「这是钩子」——那是 Claude 看完帧之后写进 dna.json 的事。

两条实现：PySceneDetect ContentDetector（默认，阈值口径与文档一致 27），
装不上时自动退到 ffmpeg `select='gt(scene,T)'`（零依赖，精度略差）。
"""

from __future__ import annotations

import asyncio
import base64
import re
from pathlib import Path

from .media import duration_of, extract_frame, ffmpeg_bin, probe, run
from .workspace import project_of, resolve_video, sub, write_json

# 碎段阈值：<0.5s 的段基本是闪帧/转场噪声，并进前一段，否则分镜表全是垃圾行
MIN_SHOT = 0.5


def _pyscenedetect_cuts(path: str, threshold: float) -> list[float] | None:
    """同步调用，外面用 to_thread 包。装不上返回 None 让调用方退到 ffmpeg。"""
    try:
        from scenedetect import ContentDetector, SceneManager, open_video
    except ImportError:
        return None
    video = open_video(path)
    mgr = SceneManager()
    mgr.add_detector(ContentDetector(threshold=threshold))
    mgr.detect_scenes(video, show_progress=False)
    return [s[0].get_seconds() for s in mgr.get_scene_list()][1:]  # 首个切点恒为 0，丢掉


async def _ffmpeg_cuts(path: str, threshold: float) -> list[float]:
    """退路：scene 打分 + showinfo 把命中帧的 pts_time 打到 stderr。

    PySceneDetect 的 27 大致对应 ffmpeg 的 0.3（reference 实测值），按此线性折算。
    """
    thr = max(0.05, min(0.95, threshold / 90.0))
    _, _, stderr = await run(
        ffmpeg_bin(), "-i", path, "-vf", f"select='gt(scene,{thr})',showinfo",
        "-an", "-f", "null", "-", timeout=1800,
    )
    return [float(m) for m in re.findall(r"pts_time:\s*([0-9]+\.?[0-9]*)", stderr)]


async def scene_split(video: str, threshold: float = 27.0, max_shots: int = 200) -> dict:
    """切镜 → shots.json。返回段表（含每段起止与时长），不含帧。"""
    path = resolve_video(video)
    dur = await duration_of(path)
    if not dur:
        raise RuntimeError("读不到视频时长，文件可能损坏")

    cuts = await asyncio.to_thread(_pyscenedetect_cuts, str(path), threshold)
    engine = "pyscenedetect"
    if cuts is None:
        cuts = await _ffmpeg_cuts(str(path), threshold)
        engine = "ffmpeg-scene"

    cuts = sorted({round(t, 3) for t in cuts if 0.2 < t < dur - 0.1})

    bounds = [0.0, *cuts, dur]
    segs: list[dict] = []
    for i in range(len(bounds) - 1):
        start, end = bounds[i], bounds[i + 1]
        if segs and end - start < MIN_SHOT:
            segs[-1]["t"][1] = round(end, 3)
            segs[-1]["duration"] = round(end - segs[-1]["t"][0], 3)
            continue
        segs.append({"idx": 0, "t": [round(start, 3), round(end, 3)], "duration": round(end - start, 3)})

    truncated = len(segs) > max_shots
    segs = segs[:max_shots]
    for i, s in enumerate(segs):
        s["idx"] = i
        # 首/中/尾三个采样点：起止用来看动作起落，中点用来认场景与人物
        st, en = s["t"]
        span = en - st
        pad = min(0.15, span * 0.08)
        s["sample_ts"] = [round(st + pad, 3), round(st + span / 2, 3), round(en - pad, 3)]

    if not segs:
        raise RuntimeError("没切出镜头（阈值过高或视频过短，调低 threshold 重试）")

    result = {
        "video": str(path),
        "engine": engine,
        "threshold": threshold,
        "duration": dur,
        "detected_cuts": len(cuts),
        "shot_count": len(segs),
        "truncated": truncated,
        # 节奏曲线直接给出来——DNA 的 rhythm.shot_durations 就是这个
        "shot_durations": [s["duration"] for s in segs],
        "shots": segs,
    }

    pid = project_of(path)
    if pid:
        result["file"] = write_json(sub(pid, "shots.json"), result)
    return result


async def frame_batch(video: str, timestamps: list[float], max_width: int = 640) -> list[tuple[float, bytes]]:
    """按时间点抽帧，返回 [(ts, jpeg_bytes)]。抽不出的点静默跳过。"""
    path = resolve_video(video)
    info = await probe(path)
    dur = float(info.get("duration") or 0)

    pid = project_of(path) or "scratch"
    cache = sub(pid, "frames", create=True)

    ts_list = [max(0.0, min(float(t), dur - 0.05 if dur else float(t))) for t in timestamps]

    async def one(ts: float) -> tuple[float, bytes] | None:
        out = cache / f"t{ts:09.3f}_w{max_width}.jpg"
        if not out.is_file() and not await extract_frame(path, ts, out, max_width):
            return None
        try:
            return ts, out.read_bytes()
        except OSError:
            return None

    # 抽帧是 IO 密集，但 ffmpeg 每个都吃满一核，限并发 4 免得把机器打死
    sem = asyncio.Semaphore(4)

    async def guarded(ts: float):
        async with sem:
            return await one(ts)

    results = await asyncio.gather(*(guarded(t) for t in ts_list))
    return [r for r in results if r]


def to_b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")

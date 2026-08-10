#!/usr/bin/env python
"""汇总分镜工程文件:shots+motion+逐镜描述+ASR+OCR → storyboard.json

    .venv/bin/python scripts/storyboard_build.py <project_id> <desc_dir>

desc_dir 下是逐镜描述 batch_*.json(VLM 产出);人物表(characters)与 subjects.ref
的映射由调用方(Claude)在产出后做跨镜 re-ID 时回填——本脚本只做确定性合并。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hotvideocopy.workspace import read_json, sub, write_json  # noqa: E402


def main(pid: str, desc_dir: str) -> None:
    shots = read_json(sub(pid, "shots.json", create=False))["shots"]
    meta = read_json(sub(pid, "meta.json", create=False), {}) or {}
    motion = {m["idx"]: m for m in (read_json(sub(pid, "motion.json", create=False), {}) or {}).get("shots", [])}
    segs = (read_json(sub(pid, "transcript.json", create=False), {}) or {}).get("segments", [])
    ocr = (read_json(sub(pid, "ocr.json", create=False), {}) or {}).get("spans", [])

    desc = {}
    for f in sorted(Path(desc_dir).glob("batch_*.json")):
        for d in json.loads(f.read_text()):
            desc[d["idx"]] = d

    out_shots = []

    def clipped_t(raw: object, start: float, end: float) -> list[float]:
        if not isinstance(raw, list) or len(raw) != 2:
            raise ValueError(f"时间轴不是 [start, end]：{raw!r}")
        a, b = float(raw[0]), float(raw[1])
        return [round(max(start, a), 3), round(min(end, b), 3)]

    for s in shots:
        idx = s.get("idx", len(out_shots))
        # 正式 MCP 输出 t；历史 r5-r8 提取脚本输出 t_start/t_end。
        raw_t = s.get("t")
        if not (isinstance(raw_t, list) and len(raw_t) == 2):
            raw_t = [s.get("t_start"), s.get("t_end")]
        if not all(isinstance(x, (int, float)) for x in raw_t):
            raise ValueError(f"shots[{idx}] 缺少合法时间轴")
        t0, t1 = map(float, raw_t)
        d = desc.get(idx, {})
        cam = d.get("camera", {})
        mv = motion.get(idx, {})
        dialogue = [{"speaker": x.get("spk"), "text": x["text"],
                     "t": clipped_t(x["t"], t0, t1)}
                    for x in segs if x["t"][0] < t1 and x["t"][1] > t0]
        overlay = [{"text": x["text"], "t": clipped_t(x["t"], t0, t1),
                    "pos": ("顶部" if x["y"] < 0.25 else "中部" if x["y"] < 0.7 else "底部字幕")}
                   for x in ocr if x["t"][0] < t1 and x["t"][1] > t0 and 0.08 < x["y"] < 0.9]
        out_shots.append({
            "idx": idx, "t": [round(t0, 3), round(t1, 3)],
            "duration": round(t1 - t0, 3),
            "camera": {"size": cam.get("size"), "move": cam.get("move"),
                       "move_cv": mv.get("label"), "angle": cam.get("angle")},
            "scene": d.get("scene"),
            "subjects": d.get("subjects", []),
            "dialogue": dialogue,
            "narration": None,
            "overlay_text": overlay,
            "transition_out": d.get("transition_out", "硬切"),
        })

    sb = {
        "meta": {"source": pid, "duration": meta.get("duration") or (out_shots[-1]["t"][1] if out_shots else 0),
                 "resolution": (f'{meta["width"]}x{meta["height"]}'
                                if meta.get("width") and meta.get("height") else None),
                 "fps": meta.get("fps"), "title": meta.get("title"), "bgm": None},
        "global": {"genre": None, "tone": None, "characters": []},
        "shots": out_shots,
    }
    p = write_json(sub(pid, "storyboard.json"), sb)
    print("storyboard →", p, f"({len(out_shots)} shots)")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])

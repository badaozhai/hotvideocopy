#!/usr/bin/env python
"""弱还原:storyboard.json → 逐镜关键帧(prompt 由 schema 字段机械拼装,不手写)。

    .venv/bin/python scripts/keyframes_from_storyboard.py <project_id>

跳过卡类镜头,人物 ref 映射到 repl_P1/repl_P2 定妆图。产出 gen/images/wr{idx}.png,可续跑。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hotvideocopy import images  # noqa: E402
from hotvideocopy.workspace import read_json, sub  # noqa: E402

CARD_HINTS = ("卡", "梗图", "插卡", "无人画面", "测试卡", "字卡")


def is_card(shot: dict) -> bool:
    return not shot.get("subjects") and any(h in (shot.get("scene") or "") for h in CARD_HINTS)


def build(shot: dict, P1: str, P2: str) -> tuple[str, list[str]]:
    cam = shot.get("camera") or {}
    refs: list[str] = []

    def ref_no(path: str) -> int:
        if path not in refs:
            refs.append(path)
        return refs.index(path) + 1

    parts = [f'{cam.get("size") or "中景"},{cam.get("angle") or "平视"}。']
    if shot.get("scene"):
        parts.append(f'场景:{shot["scene"]}。')
    for s in shot.get("subjects") or []:
        if s.get("ref") == "P1":
            who = f"第{ref_no(P1)}张参考图中的男子"
        elif s.get("ref") == "P2":
            who = f"第{ref_no(P2)}张参考图中的女子"
        else:
            who = "画面人物"
        seg = [x for x in (
            f'位于{s["pos"]}' if s.get("pos") else "",
            s.get("action") or "",
            f'表情{s["expr"]}' if s.get("expr") else "") if x]
        parts.append(who + ":" + ",".join(seg) + "。")
    parts.append("画面不带任何字幕花字。人物长相服装与对应参考图完全一致,写实电影感,不看镜头。")
    return "".join(parts), refs


async def main(pid: str) -> None:
    sb = read_json(sub(pid, "storyboard.json", create=False))
    D = sub(pid, "gen", "images", create=True)
    D.mkdir(parents=True, exist_ok=True)
    P1, P2 = str(D / "repl_P1.png"), str(D / "repl_P2.png")
    for shot in sb["shots"]:
        idx = shot["idx"]
        out = D / f"wr{idx:02d}.png"
        if out.is_file():
            continue
        if is_card(shot):
            print(f"skip #{idx}(卡)")
            continue
        prompt, refs = build(shot, P1, P2)
        try:
            await images.generate(prompt, project_id=pid, refs=refs or None,
                                  quality="2k", name=f"wr{idx:02d}")
            print(f"OK #{idx}")
        except Exception as e:
            print(f"FAIL #{idx}: {str(e)[:120]}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))

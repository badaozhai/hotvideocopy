#!/usr/bin/env python
"""script.json 数字对齐检查器 —— 把 film-language.md 的实测基准变成可执行检查。

    .venv/bin/python scripts/script_lint.py workspace/<pid>/script.json

约定 script.json 的 shots[] 每项至少有:
  dur   (秒)
  type  dialogue / reaction / action / empty / card / insert
可选: narration (旁白文本, null=无), size (CU/MCU/MS/WS)

基准(22 条实拍段子 / 739 镜实测, references/bench_report.json):
  切镜率 9-17 镜/分钟(<8 = 幻灯片红线) · 反应/对白 ≥ 0.4 · CU+MCU ≈ 1/3
  卡 ≤2s · 旁白句数 ≤ 镜头数一半 · 对白镜 3-6s、其余 2-3s 为常态
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# 切镜率按叙事形态分档(56 条实测:剧情段子型 4.3 / 恶搞整蛊 8.4 / 情侣日常 13.4)
# meta.pace: "dialogue-driven"=长对白镜承载(实拍剧情段子) / "fast"=快节奏(默认)
CUT_RATE = {"dialogue-driven": (3.5, 10.0), "fast": (8.0, 17.0)}
BENCH = {"reaction_vs_dialogue": 0.4, "cu_mcu": 0.20,
         "card_max": 2.0, "long_shot": 8.0}


def lint(path: str) -> int:
    spec = json.loads(Path(path).read_text(encoding="utf-8"))
    shots = spec.get("shots") or []
    if not shots:
        print("❌ 没有 shots[]")
        return 2

    total = sum(float(s.get("dur") or 0) for s in shots)
    n = len(shots)
    types = {}
    for s in shots:
        types.setdefault(str(s.get("type") or "?"), []).append(s)

    warns: list[str] = []
    infos: list[str] = []

    if "?" in types:
        warns.append(f"{len(types['?'])} 个镜头缺 type 字段(dialogue/reaction/action/empty/card/insert)——lint 需要它")

    pace = str((spec.get("meta") or {}).get("pace") or "fast")
    lo, hi = CUT_RATE.get(pace, CUT_RATE["fast"])
    cut_rate = n / (total / 60) if total else 0
    infos.append(f"总长 {total:.1f}s / {n} 镜 → 切镜率 {cut_rate:.1f} 镜/分(形态 {pace},基准 {lo}-{hi})")
    if cut_rate < lo:
        warns.append(f"切镜率 {cut_rate:.1f} < {lo} —— 幻灯片红线,拆拍")
    elif cut_rate > hi:
        warns.append(f"切镜率 {cut_rate:.1f} > {hi} —— 节奏可能碎,确认是否刻意")

    nd, nr = len(types.get("dialogue", [])), len(types.get("reaction", []))
    if nd:
        ratio = nr / nd
        infos.append(f"对白镜 {nd} / 反应镜 {nr} → 比 {ratio:.2f}(基准 ≥{BENCH['reaction_vs_dialogue']},实拍中位 0.53)")
        if ratio < BENCH["reaction_vs_dialogue"]:
            warns.append(f"反应镜不足(比 {ratio:.2f})——每 2 个对白镜配 1 个对方反应镜")

    sized = [s for s in shots if s.get("size") in ("CU", "MCU", "MS", "WS")]
    if sized:
        close = sum(1 for s in sized if s["size"] in ("CU", "MCU")) / len(sized)
        infos.append(f"CU+MCU 占比 {close:.0%}(基准 ~31%)")
        if close < BENCH["cu_mcu"]:
            warns.append(f"贴近人物的镜头太少({close:.0%})——情绪进不去,加近景/特写")

    # 眼线/轴线检查(手册第九章):对手戏单人镜必须声明 eyeline 且同角色全片一致
    eyelines: dict = {}
    for s in shots:
        if s.get("type") in ("dialogue", "reaction") and s.get("who"):
            e = s.get("eyeline")
            if not e:
                warns.append(f"idx={s.get('idx')} 对手戏单人镜缺 eyeline(R/L/partner/camera)")
            elif e == "camera":
                warns.append(f"idx={s.get('idx')} eyeline=camera——对手戏禁对镜头(仅 vlog 口播允许)")
            else:
                prev = eyelines.setdefault(s["who"], e)
                if e not in ("partner",) and prev not in ("partner",) and e != prev:
                    warns.append(f"idx={s.get('idx')} 角色 {s['who']} 眼线 {e} 与此前 {prev} 不一致——轴线跳了")

    narr = [s for s in shots if s.get("narration")]
    infos.append(f"旁白 {len(narr)} 句 / {n} 镜(上限 {n // 2})")
    if len(narr) > n // 2:
        warns.append(f"旁白 {len(narr)} 句超过镜头数一半——在讲故事不是在演戏,改对白/表演")

    for s in types.get("card", []):
        if float(s.get("dur") or 0) > BENCH["card_max"]:
            warns.append(f"卡镜 dur={s.get('dur')}s > {BENCH['card_max']}s——卡就是一闪")
    for s in shots:
        d = float(s.get("dur") or 0)
        if d > BENCH["long_shot"] and s.get("type") != "dialogue":
            warns.append(f"非对白镜 dur={d}s 超长(idx={s.get('idx')})——对齐基准 2-3s 或拆拍")

    print("== script_lint ==")
    for x in infos:
        print("  ·", x)
    if warns:
        print(f"⚠️  {len(warns)} 条警告:")
        for w in warns:
            print("  -", w)
        return 1
    print("✅ 全部对齐基准")
    return 0


if __name__ == "__main__":
    sys.exit(lint(sys.argv[1] if len(sys.argv) > 1 else "script.json"))

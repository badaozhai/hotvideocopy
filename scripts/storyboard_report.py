#!/usr/bin/env python
"""生成 storyboard 的确定性 QA 报告。

    .venv/bin/python scripts/storyboard_report.py <project_id>
    .venv/bin/python scripts/storyboard_report.py <project_id> --strict

报告写入 workspace/<project_id>/qc/storyboard_report.{json,md}。
它只统计和检查结构，不替代冷读 QA，也不把关键帧视觉判断伪装成自动通过。
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hotvideocopy.config import CONFIG  # noqa: E402
from storyboard_lint import EPSILON, _locate, _number, _shot_bounds, _text  # noqa: E402


def _ratio(part: int, whole: int) -> float:
    return round(part / whole, 4) if whole else 0.0


def _timed_items(shot: dict[str, Any], field: str) -> list[dict[str, Any]]:
    items = shot.get(field)
    return items if isinstance(items, list) else []


def _in_bounds(item: dict[str, Any], start: float, end: float) -> bool:
    bounds = item.get("t")
    return (isinstance(bounds, list) and len(bounds) == 2 and
            all(_number(x) for x in bounds) and
            float(bounds[0]) >= start - EPSILON and float(bounds[1]) <= end + EPSILON and
            float(bounds[1]) > float(bounds[0]))


def _semantic_counts(shots: list[dict[str, Any]]) -> dict[str, int]:
    counts = {
        "scene": 0,
        "camera": 0,
        "subjects": 0,
        "subject_complete": 0,
        "dialogue": 0,
        "overlay_text": 0,
        "transition_out": 0,
    }
    for shot in shots:
        if _text(shot.get("scene")):
            counts["scene"] += 1
        camera = shot.get("camera")
        if (isinstance(camera, dict) and
                all(_text(camera.get(field)) for field in ("size", "move", "angle"))):
            counts["camera"] += 1
        subjects = shot.get("subjects")
        if isinstance(subjects, list):
            counts["subjects"] += len(subjects)
            counts["subject_complete"] += sum(
                1 for subject in subjects
                if isinstance(subject, dict) and all(_text(subject.get(field))
                                                     for field in ("ref", "pos", "action", "expr"))
            )
        counts["dialogue"] += len(_timed_items(shot, "dialogue"))
        counts["overlay_text"] += len(_timed_items(shot, "overlay_text"))
        if _text(shot.get("transition_out")):
            counts["transition_out"] += 1
    return counts


def _check(label: str, status: str, detail: str) -> dict[str, str]:
    return {"id": label, "status": status, "detail": detail}


def build_report(source: Path, spec: dict[str, Any]) -> dict[str, Any]:
    meta = spec.get("meta") if isinstance(spec.get("meta"), dict) else {}
    global_spec = spec.get("global") if isinstance(spec.get("global"), dict) else {}
    raw_shots = spec.get("shots") if isinstance(spec.get("shots"), list) else []
    shots = [shot for shot in raw_shots if isinstance(shot, dict)]
    total = float(meta.get("duration") or 0)

    bounds = [_shot_bounds(shot) for shot in shots]
    valid_bounds = [item for item in bounds if item is not None]
    durations = [round(end - start, 3) for start, end in valid_bounds]
    gaps: list[float] = []
    overlaps: list[float] = []
    for previous, current in zip(valid_bounds, valid_bounds[1:]):
        delta = current[0] - previous[1]
        if delta > EPSILON:
            gaps.append(round(delta, 3))
        elif delta < -EPSILON:
            overlaps.append(round(-delta, 3))

    semantic = _semantic_counts(shots)
    timed_errors: list[str] = []
    dialogue_seconds = 0.0
    overlay_seconds = 0.0
    for pos, (shot, shot_bounds) in enumerate(zip(shots, bounds)):
        if shot_bounds is None:
            continue
        start, end = shot_bounds
        for field in ("dialogue", "overlay_text"):
            for item_no, item in enumerate(_timed_items(shot, field)):
                if not _in_bounds(item, start, end):
                    timed_errors.append(f"shots[{pos}].{field}[{item_no}]")
                    continue
                item_start, item_end = map(float, item["t"])
                if field == "dialogue":
                    dialogue_seconds += item_end - item_start
                else:
                    overlay_seconds += item_end - item_start

    duration_delta = abs((valid_bounds[-1][1] if valid_bounds else 0.0) - total)
    complete_shots = sum(
        1 for shot in shots
        if _text(shot.get("scene")) and isinstance(shot.get("camera"), dict)
        and all(_text(shot["camera"].get(field)) for field in ("size", "move", "angle"))
    )
    semantic_ready = (
        len(shots) > 0 and complete_shots == len(shots) and
        semantic["transition_out"] == len(shots) and not timed_errors
    )
    structural_ready = (
        len(shots) > 0 and total > 0 and not gaps and not overlaps and
        duration_delta <= EPSILON and len(valid_bounds) == len(shots)
    )

    cold_read_questions = [
        "只读 storyboard，能否说出开头钩子、冲突、反转和收尾？",
        "不看源片，能否说明每个关键动作的前因、动作和反应？",
        "不看源片，能否复述全部对白、字幕和人物关系？",
    ]
    weak_reconstruction_inputs = [
        "storyboard_lint --strict 通过",
        "每个角色 ref 都能映射到定妆图",
        "每镜至少有一张关键帧或明确标记为 card/empty",
    ]

    return {
        "schema_version": "1.0",
        "project_id": source.parent.name,
        "storyboard": str(source),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "readiness": {
            "structural": "pass" if structural_ready else "fail",
            "semantic": "pass" if semantic_ready else "warn",
            "cold_read": "pending",
            "weak_reconstruction": "pending",
            "overall": "pending",
        },
        "metrics": {
            "duration": total,
            "shot_count": len(shots),
            "shot_duration_sum": round(sum(durations), 3),
            "shot_duration_min": min(durations) if durations else 0,
            "shot_duration_median": round(statistics.median(durations), 3) if durations else 0,
            "shot_duration_max": max(durations) if durations else 0,
            "shot_durations": durations,
            "gap_seconds": round(sum(gaps), 3),
            "overlap_seconds": round(sum(overlaps), 3),
            "duration_delta": round(duration_delta, 3),
            "dialogue_count": semantic["dialogue"],
            "dialogue_seconds": round(dialogue_seconds, 3),
            "overlay_count": semantic["overlay_text"],
            "overlay_seconds": round(overlay_seconds, 3),
            "character_count": len(global_spec.get("characters", []))
            if isinstance(global_spec.get("characters"), list) else 0,
            "subject_count": semantic["subjects"],
            "scene_completion": _ratio(semantic["scene"], len(shots)),
            "camera_completion": _ratio(semantic["camera"], len(shots)),
            "transition_completion": _ratio(semantic["transition_out"], len(shots)),
            "subject_completion": _ratio(semantic["subject_complete"], semantic["subjects"]),
        },
        "checks": [
            _check("timeline_contiguous", "pass" if not gaps and not overlaps else "fail",
                   "镜头之间无明显空档或重叠" if not gaps and not overlaps else
                   f"空档 {gaps}，重叠 {overlaps}"),
            _check("duration_match", "pass" if duration_delta <= EPSILON else "fail",
                   f"末镜与 meta.duration 相差 {duration_delta:.3f}s"),
            _check("semantic_fields", "pass" if semantic_ready else "warn",
                   f"scene {semantic['scene']}/{len(shots)}，camera {semantic['camera']}/{len(shots)}，"
                   f"transition {semantic['transition_out']}/{len(shots)}"),
            _check("timed_items", "pass" if not timed_errors else "fail",
                   "对白和 overlay_text 均落在所属镜头内" if not timed_errors else
                   "越界项：" + ", ".join(timed_errors)),
            _check("cold_read_qa", "pending", "需要未看源片的代理逐题回答并记录结论"),
            _check("weak_reconstruction", "pending", "需要关键帧生成和人工拼墙比对"),
        ],
        "human_gate": {
            "cold_read": {"status": "pending", "questions": cold_read_questions, "answers": []},
            "weak_reconstruction": {"status": "pending", "inputs": weak_reconstruction_inputs,
                                    "observations": []},
        },
    }


def markdown(report: dict[str, Any]) -> str:
    m = report["metrics"]
    lines = [
        f"# Storyboard QA — {report['project_id']}",
        "",
        f"- 结构：**{report['readiness']['structural']}**",
        f"- 语义字段：**{report['readiness']['semantic']}**",
        "- 冷读 QA：**pending**",
        "- 弱还原：**pending**",
        "",
        "## 指标",
        "",
        f"- 时长：{m['duration']:.3f}s；镜头：{m['shot_count']}；切镜率："
        f"{m['shot_count'] / (m['duration'] / 60):.2f} 镜/分" if m["duration"] else "- 时长未知",
        f"- 镜头时长：{m['shot_duration_min']:.3f}s / 中位 {m['shot_duration_median']:.3f}s / {m['shot_duration_max']:.3f}s",
        f"- 对白：{m['dialogue_count']} 段，覆盖 {m['dialogue_seconds']:.3f}s；overlay：{m['overlay_count']} 段",
        f"- 字段完成度：scene {m['scene_completion']:.0%}，camera {m['camera_completion']:.0%}，"
        f"subject {m['subject_completion']:.0%}",
        "",
        "## 检查",
        "",
    ]
    for check in report["checks"]:
        lines.append(f"- `{check['status']}` {check['id']}：{check['detail']}")
    lines.extend([
        "",
        "## 人工门禁",
        "",
        "冷读 QA 与弱还原仍需人工/agent 填写；报告只负责把输入条件和未完成项固定下来。",
        "",
    ])
    return "\n".join(lines)


def run(raw: str, strict: bool = False) -> int:
    try:
        source = _locate(raw)
        spec = json.loads(source.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError) as exc:
        print(f"❌ 无法读取 storyboard：{exc}")
        return 2
    if not isinstance(spec, dict):
        print("❌ storyboard 顶层必须是对象")
        return 2

    report = build_report(source, spec)
    qc_dir = source.parent / "qc"
    qc_dir.mkdir(parents=True, exist_ok=True)
    json_path = qc_dir / "storyboard_report.json"
    md_path = qc_dir / "storyboard_report.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(markdown(report), encoding="utf-8")

    print(f"== storyboard_report ==\n  · {source}")
    print(f"  · structural={report['readiness']['structural']} semantic={report['readiness']['semantic']}")
    print(f"  · report → {json_path}")
    print(f"  · human gate → cold_read=pending weak_reconstruction=pending")
    if report["readiness"]["structural"] == "fail":
        return 1
    if strict and report["readiness"]["semantic"] != "pass":
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("storyboard", help="storyboard.json、项目目录或 project_id")
    parser.add_argument("--strict", action="store_true", help="语义字段未齐全时失败")
    args = parser.parse_args()
    return run(args.storyboard, args.strict)


if __name__ == "__main__":
    raise SystemExit(main())

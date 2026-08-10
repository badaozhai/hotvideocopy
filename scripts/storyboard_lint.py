#!/usr/bin/env python
"""storyboard.json 结构校验器。

    .venv/bin/python scripts/storyboard_lint.py <storyboard.json>
    .venv/bin/python scripts/storyboard_lint.py <project_id> --strict

基础模式只检查确定性的结构、时间轴和字段类型；--strict 还会把缺少
场景/机位/人物动作等人工描述视为错误。它不判断镜头创意是否正确。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hotvideocopy.config import CONFIG  # noqa: E402

EPSILON = 0.08


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _shot_bounds(shot: dict[str, Any]) -> tuple[float, float] | None:
    raw = shot.get("t")
    if isinstance(raw, list) and len(raw) == 2 and all(_number(x) for x in raw):
        return float(raw[0]), float(raw[1])
    return None


def _locate(raw: str) -> Path:
    p = Path(raw).expanduser()
    if p.is_file():
        return p.resolve()
    if p.is_dir():
        candidate = p / "storyboard.json"
        if candidate.is_file():
            return candidate.resolve()
    candidate = CONFIG.workspace / raw / "storyboard.json"
    if candidate.is_file():
        return candidate.resolve()
    raise FileNotFoundError(f"找不到 storyboard.json：{raw}")


def _check_timed_items(items: Any, label: str, start: float, end: float,
                       errors: list[str], strict: bool) -> None:
    if items is None:
        if strict:
            errors.append(f"{label} 缺少数组")
        return
    if not isinstance(items, list):
        errors.append(f"{label} 必须是数组")
        return
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"{label}[{i}] 必须是对象")
            continue
        if not _text(item.get("text")):
            errors.append(f"{label}[{i}] 缺 text")
        bounds = item.get("t")
        if not (isinstance(bounds, list) and len(bounds) == 2 and all(_number(x) for x in bounds)):
            errors.append(f"{label}[{i}] 的 t 必须是 [start, end]")
            continue
        a, b = map(float, bounds)
        if b <= a:
            errors.append(f"{label}[{i}] 起止时间无效：{a} -> {b}")
        if a < start - EPSILON or b > end + EPSILON:
            errors.append(f"{label}[{i}] 时间越过镜头边界：{a} -> {b}，镜头为 {start} -> {end}")


def lint(path: str, strict: bool = False) -> int:
    try:
        source = _locate(path)
    except FileNotFoundError as exc:
        print(f"❌ {exc}")
        return 2

    try:
        spec = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"❌ 无法读取 JSON：{exc}")
        return 2

    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(spec, dict):
        print("❌ storyboard 顶层必须是对象")
        return 2

    meta = spec.get("meta")
    if not isinstance(meta, dict):
        errors.append("缺少 meta 对象")
        meta = {}
    total = float(meta["duration"]) if _number(meta.get("duration")) else None
    if total is None or total <= 0:
        errors.append("meta.duration 必须是正数")

    global_spec = spec.get("global")
    if not isinstance(global_spec, dict):
        errors.append("缺少 global 对象")
        global_spec = {}
    if not isinstance(global_spec.get("characters"), list):
        (errors if strict else warnings).append("global.characters 必须是数组")

    shots = spec.get("shots")
    if not isinstance(shots, list) or not shots:
        errors.append("shots 必须是非空数组")
        shots = []

    seen: set[int] = set()
    previous_end: float | None = None
    last_end: float | None = None
    for pos, shot in enumerate(shots):
        if not isinstance(shot, dict):
            errors.append(f"shots[{pos}] 必须是对象")
            continue
        idx = shot.get("idx")
        if not isinstance(idx, int) or isinstance(idx, bool):
            errors.append(f"shots[{pos}] 缺少整数 idx")
        elif idx in seen:
            errors.append(f"shots[{pos}] idx 重复：{idx}")
        else:
            seen.add(idx)
            if idx != pos:
                warnings.append(f"shots[{pos}] idx={idx}，建议从 0 连续编号")

        bounds = _shot_bounds(shot)
        if bounds is None:
            errors.append(f"shots[{pos}] 的 t 必须是 [start, end]")
            continue
        start, end = bounds
        if start < -EPSILON or end <= start:
            errors.append(f"shots[{pos}] 时间轴无效：{start} -> {end}")
        if total is not None and end > total + EPSILON:
            errors.append(f"shots[{pos}] 结束时间 {end} 超过 meta.duration {total}")
        if previous_end is not None and start < previous_end - EPSILON:
            errors.append(f"shots[{pos}] 与前一镜重叠：{start} < {previous_end}")
        previous_end = end
        last_end = end

        duration = shot.get("duration")
        if duration is not None:
            if not _number(duration) or abs(float(duration) - (end - start)) > EPSILON:
                errors.append(f"shots[{pos}] duration 与 t 不一致")

        camera = shot.get("camera")
        if not isinstance(camera, dict):
            (errors if strict else warnings).append(f"shots[{pos}] 缺 camera 对象")
            camera = {}
        for field in ("size", "move", "angle"):
            if not _text(camera.get(field)):
                (errors if strict else warnings).append(f"shots[{pos}] camera 缺 {field}")

        scene = shot.get("scene")
        if not _text(scene):
            (errors if strict else warnings).append(f"shots[{pos}] 缺 scene")

        subjects = shot.get("subjects")
        if not isinstance(subjects, list):
            (errors if strict else warnings).append(f"shots[{pos}] subjects 必须是数组")
            subjects = []
        for j, subject in enumerate(subjects):
            if not isinstance(subject, dict):
                errors.append(f"shots[{pos}].subjects[{j}] 必须是对象")
                continue
            for field in ("ref", "pos", "action", "expr"):
                if not _text(subject.get(field)):
                    (errors if strict else warnings).append(
                        f"shots[{pos}].subjects[{j}] 缺 {field}")

        _check_timed_items(shot.get("dialogue"), f"shots[{pos}].dialogue", start, end, errors, strict)
        _check_timed_items(shot.get("overlay_text"), f"shots[{pos}].overlay_text", start, end, errors, strict)
        narration = shot.get("narration")
        if narration is not None and not _text(narration):
            errors.append(f"shots[{pos}].narration 必须是字符串或 null")
        if not _text(shot.get("transition_out")):
            (errors if strict else warnings).append(f"shots[{pos}] 缺 transition_out")

    if total is not None and last_end is not None and abs(last_end - total) > EPSILON:
        warnings.append(f"最后一镜结束于 {last_end}，与 meta.duration {total} 相差 {abs(last_end - total):.3f}s")

    mode = "strict" if strict else "basic"
    print(f"== storyboard_lint ({mode}) ==")
    print(f"  · {source} / {len(shots)} 镜 / {total or 0:.3f}s")
    if warnings:
        print(f"⚠️  {len(warnings)} 条警告:")
        for warning in warnings:
            print(f"  - {warning}")
    if errors:
        print(f"❌ {len(errors)} 条错误:")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("✅ 结构合法" + ("，严格语义字段也齐全" if strict else "；可用 --strict 检查语义字段"))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("storyboard", help="storyboard.json、项目目录或 project_id")
    parser.add_argument("--strict", action="store_true", help="缺少语义字段时也失败")
    args = parser.parse_args()
    return lint(args.storyboard, args.strict)


if __name__ == "__main__":
    raise SystemExit(main())

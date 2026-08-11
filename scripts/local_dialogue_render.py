#!/usr/bin/env python3
"""Render a dialogue manifest sequentially with the local Qwen voice model."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from hotvideocopy.local_voice import generate  # noqa: E402


async def render(manifest_path: Path, only: set[str], reuse_existing: bool = False) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    project_id = str(manifest.get("project_id") or "").strip()
    if not project_id:
        raise ValueError("dialogue manifest 缺少 project_id")
    lines = manifest.get("lines")
    if not isinstance(lines, list) or not lines:
        raise ValueError("dialogue manifest 缺少 lines")

    report_path = manifest_path.with_name("dialogue_render_report.json")
    previous = {}
    if report_path.is_file():
        try:
            old_report = json.loads(report_path.read_text(encoding="utf-8"))
            previous = {
                str(item.get("id")): item
                for item in old_report.get("results", [])
                if isinstance(item, dict) and item.get("id")
            }
        except (OSError, ValueError, TypeError):
            previous = {}
    updated = dict(previous) if only else {}
    for line in lines:
        line_id = str(line.get("id") or "").strip()
        if not line_id or (only and line_id not in only):
            continue
        cached = previous.get(line_id) if reuse_existing else None
        if cached and Path(str(cached.get("path") or "")).is_file():
            result = {
                key: value for key, value in cached.items()
                if key not in {"id", "role", "shot", "at", "visible", "max_duration", "fits"}
            }
        else:
            result = await generate(
                text=str(line.get("text") or ""),
                project_id=project_id,
                name=line_id,
                voice=str(line.get("voice") or ""),
                instruction=str(line.get("instruction") or ""),
                language=str(line.get("language") or "Chinese"),
                speed=float(line.get("speed") or 1.0),
            )
        max_duration = float(line.get("max_duration") or 0.0)
        item = {
            "id": line_id,
            "role": line.get("role"),
            "shot": line.get("shot"),
            "at": line.get("at"),
            "visible": bool(line.get("visible")),
            "max_duration": max_duration,
            **result,
        }
        item["fits"] = not max_duration or float(result["duration"]) <= max_duration
        updated[line_id] = item

    results = [
        updated[line_id]
        for line in lines
        if (line_id := str(line.get("id") or "").strip()) in updated
    ]
    oversized = [str(item["id"]) for item in results if not item.get("fits")]

    report = {
        "ok": not oversized,
        "project_id": project_id,
        "manifest": str(manifest_path),
        "rendered": len(results),
        "oversized": oversized,
        "memory_release": "one isolated model process per line",
        "results": results,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["report"] = str(report_path)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="按清单顺序生成本地角色对白并校验时长")
    parser.add_argument("manifest")
    parser.add_argument("--only", action="append", default=[])
    parser.add_argument("--reuse-existing", action="store_true")
    args = parser.parse_args()
    result = asyncio.run(render(
        Path(args.manifest).expanduser().resolve(),
        set(args.only),
        reuse_existing=args.reuse_existing,
    ))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["ok"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Install, inspect and purge workspace-scoped local media AI models."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from hotvideocopy.local_models import CATALOG, estimate_install, install, purge, status  # noqa: E402


def _print(value: object, compact: bool) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=None if compact else 2))


def main() -> None:
    raw_args = sys.argv[1:]
    compact_json = "--json" in raw_args
    raw_args = [arg for arg in raw_args if arg != "--json"]
    parser = argparse.ArgumentParser(
        description="本地语音、音乐、口型模型按需安装与清理（全部位于 workspace/.local_ai）"
    )
    parser.add_argument("--json", action="store_true", help="输出紧凑 JSON，可放在命令前后")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("status", help="查看模型、运行时与磁盘占用")
    commands.add_parser("catalog", help="查看可用模型目录")

    estimate = commands.add_parser("estimate", help="安装前容量估算")
    estimate.add_argument("component", choices=("voice", "music", "lipsync"))
    estimate.add_argument("--variant", default="")

    add = commands.add_parser("install", help="安装一个组件")
    add.add_argument("component", choices=("voice", "music", "lipsync"))
    add.add_argument("--variant", default="")

    remove = commands.add_parser("purge", help="按用户明确要求移除一个组件的模型与运行时")
    remove.add_argument("component", choices=("voice", "music", "lipsync", "all"))
    remove.add_argument("--variant", default="")
    remove.add_argument("--keep-runtime", action="store_true", help="只清模型权重，保留 Python 运行时")
    remove.add_argument(
        "--confirm-explicit-user-request",
        action="store_true",
        help="确认这是用户明确要求的清理操作；未提供时拒绝删除",
    )

    args = parser.parse_args(raw_args)
    args.json = compact_json
    try:
        if args.command == "status":
            result = status()
        elif args.command == "catalog":
            result = {
                key: {**vars(spec), "capabilities": list(spec.capabilities)}
                for key, spec in CATALOG.items()
            }
        elif args.command == "estimate":
            result = estimate_install(args.component, args.variant)
        elif args.command == "install":
            result = install(args.component, args.variant)
        else:
            result = purge(
                args.component,
                args.variant,
                args.keep_runtime,
                args.confirm_explicit_user_request,
            )
        _print(result, args.json)
    except Exception as exc:
        _print({"ok": False, "error": str(exc)}, args.json)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()

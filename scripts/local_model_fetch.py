#!/usr/bin/env python3
"""Download one Hugging Face snapshot into the workspace-scoped cache."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from huggingface_hub import snapshot_download


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--cache-dir")
    target.add_argument("--local-dir")
    parser.add_argument("--allow-pattern", action="append", default=[])
    args = parser.parse_args()

    options = {
        "repo_id": args.repo,
        "token": os.environ.get("HF_TOKEN") or None,
    }
    if args.allow_pattern:
        options["allow_patterns"] = args.allow_pattern
    if args.cache_dir:
        cache = Path(args.cache_dir).expanduser().resolve()
        cache.mkdir(parents=True, exist_ok=True)
        options["cache_dir"] = str(cache)
    else:
        local = Path(args.local_dir).expanduser().resolve()
        local.mkdir(parents=True, exist_ok=True)
        options["local_dir"] = str(local)
    snapshot = snapshot_download(**options)
    print(json.dumps({"ok": True, "repo": args.repo, "snapshot": snapshot}))


if __name__ == "__main__":
    main()

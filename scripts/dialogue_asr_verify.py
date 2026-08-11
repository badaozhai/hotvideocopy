#!/usr/bin/env python3
"""Verify rendered dialogue against its manifest with a cached Whisper model."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def normalize(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z\u3400-\u9fff]", "", str(text or "")).lower()


def edit_distance(left: str, right: str) -> int:
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for row, lchar in enumerate(left, start=1):
        current = [row]
        for column, rchar in enumerate(right, start=1):
            current.append(min(
                current[-1] + 1,
                previous[column] + 1,
                previous[column - 1] + (lchar != rchar),
            ))
        previous = current
    return previous[-1]


def verify(manifest_path: Path, model_name: str, max_cer: float, only: set[str]) -> dict:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("缺少 faster-whisper，请先安装项目的 ASR 依赖") from exc

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    render_path = manifest_path.with_name("dialogue_render_report.json")
    render = json.loads(render_path.read_text(encoding="utf-8"))
    rendered = {
        str(item.get("id")): item
        for item in render.get("results", [])
        if isinstance(item, dict) and item.get("id")
    }

    model = WhisperModel(
        model_name,
        device="cpu",
        compute_type="int8",
        local_files_only=True,
    )
    output = manifest_path.with_name("dialogue_asr_report.json")
    updated = {}
    if only and output.is_file():
        try:
            previous = json.loads(output.read_text(encoding="utf-8"))
            updated = {
                str(item.get("id")): item
                for item in previous.get("results", [])
                if isinstance(item, dict) and item.get("id")
            }
        except (OSError, ValueError, TypeError):
            updated = {}
    for line in manifest.get("lines", []):
        line_id = str(line.get("id") or "").strip()
        if not line_id or (only and line_id not in only):
            continue
        audio = Path(str(rendered.get(line_id, {}).get("path") or ""))
        if not audio.is_file():
            updated[line_id] = {
                "id": line_id,
                "expected": str(line.get("text") or ""),
                "ok": False,
                "error": "missing rendered audio",
            }
            continue
        segments, info = model.transcribe(
            str(audio),
            language="zh",
            vad_filter=True,
            beam_size=5,
            initial_prompt="以下是自然的中文农村采访对白，使用规范简体中文。",
        )
        transcript = "".join(segment.text.strip() for segment in segments)
        expected_normalized = normalize(str(line.get("text") or ""))
        transcript_normalized = normalize(transcript)
        distance = edit_distance(expected_normalized, transcript_normalized)
        cer = distance / max(1, len(expected_normalized))
        updated[line_id] = {
            "id": line_id,
            "role": line.get("role"),
            "expected": str(line.get("text") or ""),
            "transcript": transcript,
            "normalized_expected": expected_normalized,
            "normalized_transcript": transcript_normalized,
            "edit_distance": distance,
            "cer": round(cer, 4),
            "exact": expected_normalized == transcript_normalized,
            "language_probability": round(float(info.language_probability or 0), 4),
            "ok": bool(transcript_normalized) and cer <= max_cer,
            "audio": str(audio),
        }

    results = [
        updated[line_id]
        for line in manifest.get("lines", [])
        if (line_id := str(line.get("id") or "").strip()) in updated
    ]

    failed = [item["id"] for item in results if not item.get("ok")]
    exact = [item["id"] for item in results if item.get("exact")]
    report = {
        "ok": not failed,
        "project_id": manifest.get("project_id"),
        "manifest": str(manifest_path),
        "render_report": str(render_path),
        "model": f"faster-whisper/{model_name}",
        "local_files_only": True,
        "max_cer": max_cer,
        "verified": len(results),
        "exact_count": len(exact),
        "failed": failed,
        "results": results,
    }
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["report"] = str(output)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="逐句回验本地配音文字")
    parser.add_argument("manifest")
    parser.add_argument("--model", default="large-v3")
    parser.add_argument("--max-cer", type=float, default=0.2)
    parser.add_argument("--only", action="append", default=[])
    args = parser.parse_args()
    result = verify(
        Path(args.manifest).expanduser().resolve(),
        args.model,
        args.max_cer,
        set(args.only),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["ok"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()

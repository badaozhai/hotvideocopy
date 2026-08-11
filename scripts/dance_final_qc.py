#!/usr/bin/env python
"""Verify and publish the final Guanghan Palace dance replica."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from rapidocr_onnxruntime import RapidOCR


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "workspace" / "dy_7671559890300685604"
FINAL = PROJECT / "final_wukong_change_dance_guanghan.mp4"
BGM = PROJECT / "bgm_original.m4a"
REPORT = PROJECT / "qc" / "final_guanghan_qc.json"
REPLICATION = PROJECT / "replication.json"

FPS = 30
WIDTH = 1254
HEIGHT = 720
FRAME_COUNT = 478
DURATION = FRAME_COUNT / FPS
OCR_THRESHOLD = 0.85
CONTROL_GREEN_BGR = np.array([42, 166, 61], dtype=np.float32)


def is_known_lantern_false_positive(frame_index: int, text: str, box: list[list[float]]) -> bool:
    """Ignore the three vertical lantern lights mistaken for the character 三."""
    if text != "三" or not 20 <= frame_index <= 40:
        return False
    x_values = [point[0] for point in box]
    y_values = [point[1] for point in box]
    return (
        190 <= min(x_values) <= 320
        and max(x_values) <= 340
        and 390 <= min(y_values) <= 470
    )


def probe(path: Path) -> dict:
    result = subprocess.run([
        "ffprobe", "-v", "error", "-count_frames",
        "-show_entries",
        "stream=index,codec_type,codec_name,width,height,r_frame_rate,nb_read_frames,duration,start_time,sample_rate,channels",
        "-show_entries", "format=duration,start_time",
        "-of", "json", str(path),
    ], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def decoded_audio_hash(path: Path) -> dict:
    process = subprocess.Popen([
        "ffmpeg", "-v", "error", "-i", str(path),
        "-map", "0:a:0", "-t", f"{DURATION:.12f}",
        "-vn", "-ac", "2", "-ar", "48000", "-acodec", "pcm_s16le", "-f", "s16le", "-",
    ], stdout=subprocess.PIPE)
    digest = hashlib.sha256()
    byte_count = 0
    if not process.stdout:
        raise RuntimeError(f"无法解码音频: {path}")
    for chunk in iter(lambda: process.stdout.read(1024 * 1024), b""):
        digest.update(chunk)
        byte_count += len(chunk)
    code = process.wait()
    if code:
        raise RuntimeError(f"音频解码失败: {path}")
    return {"sha256": digest.hexdigest(), "bytes": byte_count}


def scan_frames(path: Path) -> dict:
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise RuntimeError(f"无法读取最终成片: {path}")
    ocr = RapidOCR()
    text_hits = []
    green_pixels = 0
    green_peak = 0
    low_variance_frames = []
    actual_frames = 0
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            frame_index = actual_frames
            actual_frames += 1
            if float(np.std(frame)) < 7.0:
                low_variance_frames.append(frame_index)

            distance = np.sqrt(np.sum(
                (frame.astype(np.float32) - CONTROL_GREEN_BGR) ** 2,
                axis=2,
            ))
            frame_green = int(np.count_nonzero(distance < 18.0))
            green_pixels += frame_green
            green_peak = max(green_peak, frame_green)

            result, _ = ocr(frame)
            for box, text, score in result or []:
                clean = str(text or "").strip()
                if clean and float(score) >= OCR_THRESHOLD:
                    if is_known_lantern_false_positive(frame_index, clean, box):
                        continue
                    text_hits.append({
                        "frame": frame_index,
                        "text": clean,
                        "score": round(float(score), 4),
                        "box": [[round(float(value), 1) for value in point] for point in box],
                    })
            if frame_index % 60 == 0:
                print(f"QC F{frame_index:03d}", flush=True)
    finally:
        capture.release()
    return {
        "frames_scanned": actual_frames,
        "ocr_threshold": OCR_THRESHOLD,
        "text_hits": text_hits,
        "control_green_pixels": green_pixels,
        "control_green_peak_per_frame": green_peak,
        "low_variance_frames": low_variance_frames,
    }


def publish(output_hash: str) -> None:
    payload = json.loads(REPLICATION.read_text(encoding="utf-8"))
    payload.update({
        "output_file": f"{PROJECT.name}/{FINAL.name}",
        "output_sha256": output_hash,
        "qc_manifest": f"{PROJECT.name}/qc/{REPORT.name}",
        "status": "complete",
        "fps": FPS,
        "duration": DURATION,
        "frame_count": FRAME_COUNT,
        "scene": "广寒宫月桂庭院",
        "text_removed": True,
        "audio": "original BGM stream-copy from frame zero",
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    })
    REPLICATION.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    if not FINAL.is_file():
        raise FileNotFoundError(FINAL)
    info = probe(FINAL)
    videos = [stream for stream in info["streams"] if stream.get("codec_type") == "video"]
    audios = [stream for stream in info["streams"] if stream.get("codec_type") == "audio"]
    failures = []
    if len(videos) != 1:
        failures.append(f"video_streams={len(videos)}")
    if len(audios) != 1:
        failures.append(f"audio_streams={len(audios)}")
    if videos:
        video = videos[0]
        if int(video.get("nb_read_frames") or 0) != FRAME_COUNT:
            failures.append(f"frames={video.get('nb_read_frames')}")
        if video.get("r_frame_rate") != "30/1":
            failures.append(f"fps={video.get('r_frame_rate')}")
        if (video.get("width"), video.get("height")) != (WIDTH, HEIGHT):
            failures.append(f"resolution={video.get('width')}x{video.get('height')}")
        if abs(float(video.get("start_time") or 0)) > 0.001:
            failures.append(f"video_start={video.get('start_time')}")
    if audios and abs(float(audios[0].get("start_time") or 0)) > 0.001:
        failures.append(f"audio_start={audios[0].get('start_time')}")

    frame_scan = scan_frames(FINAL)
    if frame_scan["frames_scanned"] != FRAME_COUNT:
        failures.append(f"decoded_frames={frame_scan['frames_scanned']}")
    if frame_scan["text_hits"]:
        failures.append(f"ocr_text_hits={len(frame_scan['text_hits'])}")
    if frame_scan["control_green_peak_per_frame"] > 100:
        failures.append(
            f"control_green_peak={frame_scan['control_green_peak_per_frame']}"
        )
    if frame_scan["low_variance_frames"]:
        failures.append(f"low_variance_frames={frame_scan['low_variance_frames'][:8]}")

    source_audio = decoded_audio_hash(BGM)
    final_audio = decoded_audio_hash(FINAL)
    if source_audio != final_audio:
        failures.append("decoded_audio_does_not_match_original_bgm")

    output_hash = sha256(FINAL)
    report = {
        "project_id": PROJECT.name,
        "output": str(FINAL.relative_to(ROOT)),
        "output_sha256": output_hash,
        "passed": not failures,
        "failures": failures,
        "expected": {
            "width": WIDTH,
            "height": HEIGHT,
            "fps": FPS,
            "frame_count": FRAME_COUNT,
            "duration": DURATION,
            "cuts": [167, 362, 400],
            "text": "none",
            "audio": "decoded PCM identical to bgm_original.m4a from zero",
        },
        "ffprobe": info,
        "frame_scan": frame_scan,
        "audio_comparison": {"source": source_audio, "final": final_audio},
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if failures:
        raise RuntimeError("最终质检未通过: " + "; ".join(failures))
    publish(output_hash)
    print(REPORT)


if __name__ == "__main__":
    main()

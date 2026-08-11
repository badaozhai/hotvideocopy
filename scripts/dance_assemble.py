#!/usr/bin/env python
"""Assemble the Guanghan Palace dance on the exact 478-frame source clock."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "workspace" / "dy_7671559890300685604"
CLIP_DIR = PROJECT / "gen" / "clips"
RAW_DIR = PROJECT / "gen" / "normalized_raw"
NORMALIZED_DIR = PROJECT / "gen" / "normalized_guanghan"
QC_DIR = PROJECT / "qc"
MOTION_TRACKS = PROJECT / "motion" / "motion_tracks.json"
FINAL = PROJECT / "final_wukong_change_dance_guanghan.mp4"
VIDEO_ONLY = NORMALIZED_DIR / "assembled_478f_video.mp4"

FPS = 30
WIDTH = 1254
HEIGHT = 720
TOTAL_FRAMES = 478
TARGET_DURATION = TOTAL_FRAMES / FPS


@dataclass(frozen=True)
class Segment:
    key: str
    source_name: str
    target_frames: int
    source_clock_frames: int
    global_start: int
    correct_hands: bool = True


SEGMENTS = (
    Segment("s00", "dance_green_guanghan_s00_v6_refs.mp4", 167, 167, 0),
    # The available middle render already covers the complete 233-frame span.
    Segment("s01", "dance_green_guanghan_s01_v6_refs.mp4", 233, 233, 167),
    Segment("s02", "dance_green_guanghan_s02_v6_refs.mp4", 78, 78, 400),
)


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def probe(path: Path, count_frames: bool = False) -> dict:
    command = ["ffprobe", "-v", "error"]
    if count_frames:
        command += ["-count_frames"]
    command += [
        "-show_entries",
        "stream=index,codec_type,codec_name,width,height,r_frame_rate,avg_frame_rate,duration,nb_frames,nb_read_frames,start_time",
        "-show_entries",
        "format=duration,start_time",
        "-of",
        "json",
        str(path),
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def video_stream(info: dict) -> dict:
    return next(stream for stream in info["streams"] if stream.get("codec_type") == "video")


def normalize(source: Path, output: Path, spec: Segment) -> dict:
    source_info = probe(source, count_frames=True)
    stream = video_stream(source_info)
    source_duration = float(stream.get("duration") or source_info["format"]["duration"])
    full_clock_duration = spec.source_clock_frames / FPS
    if source_duration <= 0:
        raise RuntimeError(f"生成片段时长无效: {source}")

    output.parent.mkdir(parents=True, exist_ok=True)
    ratio = full_clock_duration / source_duration
    vf = (
        f"setpts={ratio:.12f}*PTS,"
        "minterpolate=fps=30:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1,"
        "tpad=stop_mode=clone:stop_duration=0.3,"
        f"trim=end_frame={spec.target_frames},setpts=PTS-STARTPTS"
    )
    run([
        "ffmpeg", "-y", "-v", "error", "-i", str(source),
        "-vf", vf, "-an", "-frames:v", str(spec.target_frames), "-r", str(FPS),
        "-c:v", "libx264", "-preset", "slow", "-crf", "15", "-pix_fmt", "yuv420p",
        str(output),
    ])

    normalized_info = probe(output, count_frames=True)
    normalized_stream = video_stream(normalized_info)
    actual_frames = int(normalized_stream.get("nb_read_frames") or 0)
    if actual_frames != spec.target_frames:
        raise RuntimeError(
            f"标准化片段帧数错误: {output.name} {actual_frames} != {spec.target_frames}"
        )
    return {
        "key": spec.key,
        "source": str(source.relative_to(ROOT)),
        "source_duration": source_duration,
        "source_frames": int(stream.get("nb_read_frames") or stream.get("nb_frames") or 0),
        "source_clock_frames": spec.source_clock_frames,
        "target": str(output.relative_to(ROOT)),
        "target_frames": spec.target_frames,
        "global_start_frame": spec.global_start,
        "retime_ratio": ratio,
    }


def load_female_landmarks() -> list[list[list[float]]]:
    payload = json.loads(MOTION_TRACKS.read_text(encoding="utf-8"))
    frames = payload.get("frames") or []
    if len(frames) != TOTAL_FRAMES:
        raise RuntimeError(f"动作轨帧数错误: {len(frames)} != {TOTAL_FRAMES}")
    return [row["female"]["landmarks"] for row in frames]


def hand_region_mask(landmarks: list[list[float]]) -> np.ndarray:
    mask = np.zeros((HEIGHT, WIDTH), dtype=np.uint8)
    points = np.array([
        [row[0] * WIDTH, row[1] * HEIGHT, row[3]] for row in landmarks
    ], dtype=np.float32)
    shoulder_width = float(np.linalg.norm(points[11, :2] - points[12, :2]))
    # Generated wrists can drift up to ~80 px from the source landmarks even
    # when the overall pose is correct, so keep a generous role-local region.
    radius = int(np.clip(shoulder_width * 0.36, 128, 148))
    for index in (15, 16, 17, 18, 19, 20, 21, 22):
        x, y, visibility = points[index]
        if visibility < 0.08 or not (-radius <= x < WIDTH + radius and -radius <= y < HEIGHT + radius):
            continue
        cv2.circle(mask, (int(round(x)), int(round(y))), radius, 255, -1, cv2.LINE_AA)
    return mask


def correct_hand_control_color(
    source: Path,
    output: Path,
    spec: Segment,
    female_landmarks: list[list[list[float]]],
) -> dict:
    if not spec.correct_hands:
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, output)
        return {"enabled": False, "frames_touched": 0, "pixels_touched": 0}

    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        raise RuntimeError(f"无法读取标准化片段: {source}")
    output.parent.mkdir(parents=True, exist_ok=True)
    encoder = subprocess.Popen([
        "ffmpeg", "-y", "-v", "error",
        "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{WIDTH}x{HEIGHT}",
        "-r", str(FPS), "-i", "-", "-an", "-frames:v", str(spec.target_frames),
        "-c:v", "libx264", "-preset", "slow", "-crf", "15", "-pix_fmt", "yuv420p",
        str(output),
    ], stdin=subprocess.PIPE)

    frames_touched = 0
    pixels_touched = 0
    try:
        for local_frame in range(spec.target_frames):
            ok, frame = capture.read()
            if not ok:
                raise RuntimeError(f"肤色修正时片段 {spec.key} 在第 {local_frame} 帧提前结束")
            global_frame = spec.global_start + local_frame
            region = hand_region_mask(female_landmarks[global_frame])
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            blue, green, red = cv2.split(frame)
            red_hue = (hsv[:, :, 0] <= 12) | (hsv[:, :, 0] >= 165)
            saturated = hsv[:, :, 1] >= 35
            red_dominant = (
                (red.astype(np.float32) >= green.astype(np.float32) * 1.08)
                & (red.astype(np.float32) >= blue.astype(np.float32) * 1.10)
            )
            pink_balance = (
                blue.astype(np.float32) >= green.astype(np.float32) * 0.72
            )
            selected = red_hue & saturated & red_dominant & pink_balance & (region > 0)
            selected_count = int(np.count_nonzero(selected))
            if selected_count:
                hard_mask = selected.astype(np.uint8) * 255
                hard_mask = cv2.morphologyEx(
                    hard_mask,
                    cv2.MORPH_CLOSE,
                    np.ones((3, 3), dtype=np.uint8),
                )
                hard_mask = cv2.dilate(
                    hard_mask,
                    cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)),
                )
                hard_mask[region == 0] = 0
                alpha = cv2.GaussianBlur(hard_mask, (0, 0), 1.0).astype(np.float32) / 255.0
                alpha = np.minimum(alpha * 0.98, 0.98)[:, :, None]
                luma = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
                target = np.stack((
                    np.clip(luma * 0.95 + 38, 0, 255),
                    np.clip(luma * 1.00 + 42, 0, 255),
                    np.clip(luma * 1.05 + 48, 0, 255),
                ), axis=2)
                frame = np.clip(
                    frame.astype(np.float32) * (1.0 - alpha) + target * alpha,
                    0,
                    255,
                ).astype(np.uint8)
                frames_touched += 1
                pixels_touched += selected_count
            if not encoder.stdin:
                raise RuntimeError("肤色修正编码器不可写")
            encoder.stdin.write(frame.tobytes())
    finally:
        capture.release()
        if encoder.stdin:
            encoder.stdin.close()
        code = encoder.wait()
        if code:
            raise RuntimeError(f"肤色修正编码失败: {code}")

    corrected_info = probe(output, count_frames=True)
    corrected_frames = int(video_stream(corrected_info).get("nb_read_frames") or 0)
    if corrected_frames != spec.target_frames:
        raise RuntimeError(
            f"肤色修正片段帧数错误: {output.name} {corrected_frames} != {spec.target_frames}"
        )
    return {
        "enabled": True,
        "frames_touched": frames_touched,
        "pixels_touched": pixels_touched,
        "selection": "female wrist/hand landmarks intersecting saturated red pixels only",
    }


def make_qc_assets(final: Path) -> None:
    run([
        "ffmpeg", "-y", "-v", "error", "-i", str(final),
        "-vf", "select='not(mod(n,30))',scale=418:240,tile=4x4",
        "-frames:v", "1", str(QC_DIR / "guanghan_final_contact_sheet.jpg"),
    ])
    for frame in (0, TOTAL_FRAMES - 1):
        name = "first" if frame == 0 else "last"
        run([
            "ffmpeg", "-y", "-v", "error", "-i", str(final),
            "-vf", f"select=eq(n\\,{frame})", "-frames:v", "1",
            str(QC_DIR / f"guanghan_final_{name}.jpg"),
        ])
    for cut in (167, 362, 400):
        run([
            "ffmpeg", "-y", "-v", "error", "-i", str(final),
            "-vf", f"select='eq(n,{cut - 1})+eq(n,{cut})',scale=627:360,tile=2x1",
            "-frames:v", "1", str(QC_DIR / f"guanghan_boundary_{cut}.jpg"),
        ])


def assemble() -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)
    QC_DIR.mkdir(parents=True, exist_ok=True)
    female_landmarks = load_female_landmarks()
    rows = []
    normalized = []
    for spec in SEGMENTS:
        source = CLIP_DIR / spec.source_name
        if not source.is_file():
            raise FileNotFoundError(f"外部编辑片段尚未下载: {source}")
        raw = RAW_DIR / f"{spec.key}_{spec.target_frames}f.mp4"
        row = normalize(source, raw, spec)
        output = NORMALIZED_DIR / f"{spec.key}_{spec.target_frames}f.mp4"
        row["hand_color_correction"] = correct_hand_control_color(
            raw, output, spec, female_landmarks
        )
        row["assembled_source"] = str(output.relative_to(ROOT))
        rows.append(row)
        normalized.append(output)

    inputs: list[str] = []
    for path in normalized:
        inputs += ["-i", str(path)]
    concat_inputs = "".join(f"[{index}:v]" for index in range(len(normalized)))
    filters = f"{concat_inputs}concat=n={len(normalized)}:v=1:a=0[v]"
    run([
        "ffmpeg", "-y", "-v", "error", *inputs,
        "-filter_complex", filters, "-map", "[v]",
        "-frames:v", str(TOTAL_FRAMES), "-r", str(FPS),
        "-c:v", "libx264", "-preset", "slow", "-crf", "15", "-pix_fmt", "yuv420p",
        "-an", "-movflags", "+faststart", str(VIDEO_ONLY),
    ])
    run([
        "ffmpeg", "-y", "-v", "error",
        "-i", str(VIDEO_ONLY), "-i", str(PROJECT / "bgm_original.m4a"),
        "-map", "0:v:0", "-map", "1:a:0", "-c", "copy",
        "-t", f"{TARGET_DURATION:.12f}", "-movflags", "+faststart", str(FINAL),
    ])

    final_info = probe(FINAL, count_frames=True)
    final_video = video_stream(final_info)
    actual_frames = int(final_video.get("nb_read_frames") or 0)
    audio_streams = [
        stream for stream in final_info["streams"] if stream.get("codec_type") == "audio"
    ]
    failures = []
    if actual_frames != TOTAL_FRAMES:
        failures.append(f"frames {actual_frames} != {TOTAL_FRAMES}")
    if final_video.get("r_frame_rate") != "30/1":
        failures.append(f"fps {final_video.get('r_frame_rate')} != 30/1")
    if (final_video.get("width"), final_video.get("height")) != (WIDTH, HEIGHT):
        failures.append(
            f"size {(final_video.get('width'), final_video.get('height'))} != {(WIDTH, HEIGHT)}"
        )
    if len(audio_streams) != 1:
        failures.append(f"audio streams {len(audio_streams)} != 1")
    if failures:
        raise RuntimeError("最终成片规格错误: " + "; ".join(failures))

    make_qc_assets(FINAL)
    report = {
        "project_id": PROJECT.name,
        "mode": "guanghan_pose_control_cut_aware_retime",
        "fps": FPS,
        "frame_count": TOTAL_FRAMES,
        "video_duration": TARGET_DURATION,
        "resolution": [WIDTH, HEIGHT],
        "source_cuts": [167, 400],
        "assembly_frames": [167, 195, 38, 78],
        "bgm": "bgm_original.m4a",
        "bgm_policy": "original source AAC stream-copy from zero, trimmed on the 478-frame clock",
        "characters": {
            "male": "assets/characters/wukong.png",
            "female": "assets/characters/change.png",
        },
        "scene": "广寒宫月桂庭院",
        "text_policy": "no source text, subtitles, labels, logos, or watermarks",
        "segments": rows,
        "output": str(FINAL.relative_to(ROOT)),
        "ffprobe": final_info,
    }
    (QC_DIR / "final_guanghan_manifest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return FINAL


if __name__ == "__main__":
    print(assemble())

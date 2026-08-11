#!/usr/bin/env python
"""Render a text-free two-role close-up control for source frames 362-399."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/private/tmp/hvc-mpl")
os.environ.setdefault("XDG_CACHE_HOME", "/private/tmp/hvc-cache")

import cv2
import numpy as np
from rtmlib import Wholebody


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "workspace" / "dy_7671559890300685604"
SOURCE = PROJECT / "source.mp4"
OUTPUT = (
    PROJECT
    / "motion_segments"
    / "pose_green_assetcolor_closeup_s01b_f362_399.mp4"
)
QC_SHEET = PROJECT / "qc" / "pose_closeup_control_sheet.jpg"
QC_MANIFEST = PROJECT / "qc" / "pose_closeup_control.json"
MODEL_DIR = Path("/private/tmp/hvc-rtmlib-cache/rtmlib/hub/checkpoints")
DETECTOR = MODEL_DIR / "yolox_m_8xb8-300e_humanart-c2c7a14a.onnx"
POSE = MODEL_DIR / "rtmw-dw-x-l_simcc-cocktail14_270e-384x288_20231122.onnx"

WIDTH = 1254
HEIGHT = 720
FPS = 30
START_FRAME = 362
END_FRAME = 399
FRAME_COUNT = END_FRAME - START_FRAME + 1

GREEN = (42, 166, 61)
GREEN_DARK = (34, 139, 49)
GOLD = (45, 170, 225)
SILVER = (235, 235, 235)


def shade(color: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    return tuple(int(np.clip(channel * amount, 0, 255)) for channel in color)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def open_encoder(path: Path) -> subprocess.Popen:
    path.parent.mkdir(parents=True, exist_ok=True)
    return subprocess.Popen([
        "ffmpeg", "-y", "-v", "error",
        "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{WIDTH}x{HEIGHT}",
        "-r", str(FPS), "-i", "-", "-an", "-frames:v", str(FRAME_COUNT),
        "-c:v", "libx264", "-preset", "slow", "-crf", "14", "-pix_fmt", "yuv420p",
        str(path),
    ], stdin=subprocess.PIPE)


def male_box(boxes: np.ndarray) -> np.ndarray:
    candidates = [
        box for box in boxes
        if (box[0] + box[2]) / 2 < WIDTH * 0.75
        and box[2] - box[0] > WIDTH * 0.35
    ]
    if not candidates:
        raise RuntimeError("近景帧未检测到前景男角色")
    return max(candidates, key=lambda box: (box[2] - box[0]) * (box[3] - box[1]))


def face_geometry(keypoints: np.ndarray, role: str) -> dict[str, float]:
    left_eye = keypoints[1].astype(np.float64)
    right_eye = keypoints[2].astype(np.float64)
    nose = keypoints[0].astype(np.float64)
    eye_mid = (left_eye + right_eye) / 2.0
    eye_distance = float(np.linalg.norm(left_eye - right_eye))
    angle = float(np.degrees(np.arctan2(
        left_eye[1] - right_eye[1], left_eye[0] - right_eye[0]
    )))

    if role == "male":
        width = float(np.clip(eye_distance * 2.15, 270, 390))
        height = width * 1.24
        center = eye_mid + (nose - eye_mid) * 0.58
        center[1] -= height * 0.02
    else:
        width = float(np.clip(eye_distance * 1.78, 145, 255))
        height = width * 1.22
        center = eye_mid + (nose - eye_mid) * 0.62
        center[1] -= height * 0.015

    return {
        "center_x": float(center[0]),
        "center_y": float(center[1]),
        "width": width,
        "height": height,
        "angle": angle,
        "nose_x": float(nose[0]),
        "nose_y": float(nose[1]),
    }


def smooth(rows: list[dict[str, float]], radius: int = 2) -> list[dict[str, float]]:
    output: list[dict[str, float]] = []
    keys = tuple(rows[0])
    for index in range(len(rows)):
        start = max(0, index - radius)
        end = min(len(rows), index + radius + 1)
        output.append({
            key: float(np.median([row[key] for row in rows[start:end]]))
            for key in keys
        })
    return output


def draw_role(
    frame: np.ndarray,
    geometry: dict[str, float],
    color: tuple[int, int, int],
    role: str,
) -> None:
    cx = int(round(geometry["center_x"]))
    cy = int(round(geometry["center_y"]))
    width = int(round(geometry["width"]))
    height = int(round(geometry["height"]))
    angle = geometry["angle"]
    outline = shade(color, 0.50)
    highlight = shade(color, 1.08)

    shoulder_y = int(round(cy + height * (0.46 if role == "male" else 0.48)))
    top_half = width * (0.72 if role == "male" else 0.76)
    bottom_half = width * (1.65 if role == "male" else 1.30)
    torso = np.array([
        [int(cx - top_half), shoulder_y],
        [int(cx + top_half), shoulder_y],
        [int(cx + bottom_half), HEIGHT + 8],
        [int(cx - bottom_half), HEIGHT + 8],
    ], dtype=np.int32)
    cv2.fillConvexPoly(frame, torso, color, cv2.LINE_AA)
    cv2.polylines(frame, [torso], True, outline, max(4, width // 36), cv2.LINE_AA)

    axes = (max(20, width // 2), max(24, height // 2))
    cv2.ellipse(frame, (cx, cy), (axes[0] + 5, axes[1] + 5), angle, 0, 360, outline, -1, cv2.LINE_AA)
    cv2.ellipse(frame, (cx, cy), axes, angle, 0, 360, color, -1, cv2.LINE_AA)

    nose = (int(round(geometry["nose_x"])), int(round(geometry["nose_y"])))
    marker_radius = max(5, width // 28)
    cv2.line(frame, (cx, cy), nose, outline, max(3, marker_radius // 2), cv2.LINE_AA)
    cv2.circle(frame, nose, marker_radius + 2, outline, -1, cv2.LINE_AA)
    cv2.circle(frame, nose, marker_radius, highlight, -1, cv2.LINE_AA)


def detect_tracks(model: Wholebody) -> tuple[list[dict[str, float]], list[dict[str, float]]]:
    capture = cv2.VideoCapture(str(SOURCE))
    capture.set(cv2.CAP_PROP_POS_FRAMES, START_FRAME)
    male_rows: list[dict[str, float]] = []
    female_rows: list[dict[str, float]] = []
    female_roi = [600, 150, WIDTH - 1, HEIGHT - 1]
    try:
        for frame_index in range(START_FRAME, END_FRAME + 1):
            ok, frame = capture.read()
            if not ok:
                raise RuntimeError(f"源视频在第 {frame_index} 帧提前结束")
            boxes = model.det_model(frame)
            male_keypoints, _ = model.pose_model(frame, bboxes=[male_box(boxes)])
            female_keypoints, _ = model.pose_model(frame, bboxes=[female_roi])
            male_rows.append(face_geometry(male_keypoints[0], "male"))
            female_rows.append(face_geometry(female_keypoints[0], "female"))
            if frame_index % 10 == 2 or frame_index == END_FRAME:
                print(f"track F{frame_index:03d}", flush=True)
    finally:
        capture.release()
    return smooth(male_rows), smooth(female_rows)


def render(
    male_rows: list[dict[str, float]],
    female_rows: list[dict[str, float]],
) -> None:
    encoder = open_encoder(OUTPUT)
    try:
        for offset in range(FRAME_COUNT):
            frame = np.full((HEIGHT, WIDTH, 3), GREEN, dtype=np.uint8)
            cv2.rectangle(frame, (0, int(HEIGHT * 0.92)), (WIDTH, HEIGHT), GREEN_DARK, -1)
            draw_role(frame, female_rows[offset], SILVER, "female")
            draw_role(frame, male_rows[offset], GOLD, "male")
            if not encoder.stdin:
                raise RuntimeError("控制片编码器不可写")
            encoder.stdin.write(frame.tobytes())
    finally:
        if encoder.stdin:
            encoder.stdin.close()
        code = encoder.wait()
        if code:
            raise RuntimeError(f"控制片编码失败: {code}")


def make_sheet() -> None:
    QC_SHEET.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-i", str(OUTPUT),
        "-vf", "select='eq(n,0)+eq(n,4)+eq(n,8)+eq(n,12)+eq(n,16)+eq(n,20)+eq(n,24)+eq(n,28)+eq(n,33)+eq(n,37)',scale=627:360,tile=5x2",
        "-frames:v", "1", str(QC_SHEET),
    ], check=True)


def main() -> None:
    for model_path in (DETECTOR, POSE):
        if not model_path.is_file():
            raise FileNotFoundError(model_path)
    model = Wholebody(
        det=str(DETECTOR),
        det_input_size=(640, 640),
        pose=str(POSE),
        pose_input_size=(288, 384),
        backend="onnxruntime",
        device="cpu",
        to_openpose=False,
    )
    male_rows, female_rows = detect_tracks(model)
    render(male_rows, female_rows)
    make_sheet()
    QC_MANIFEST.write_text(json.dumps({
        "source": str(SOURCE.relative_to(ROOT)),
        "output": str(OUTPUT.relative_to(ROOT)),
        "source_frame_start": START_FRAME,
        "source_frame_end": END_FRAME,
        "frame_count": FRAME_COUNT,
        "fps": FPS,
        "width": WIDTH,
        "height": HEIGHT,
        "role_mapping": {"gold": "孙悟空", "silver_white": "嫦娥"},
        "contains_source_pixels": False,
        "contains_text": False,
        "sha256": sha256(OUTPUT),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(OUTPUT)


if __name__ == "__main__":
    main()

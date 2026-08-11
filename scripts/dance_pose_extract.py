#!/usr/bin/env python
"""Extract two role-locked pose tracks and render mannequin control videos for the dance replica."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/private/tmp/hvc-mpl")
os.environ.setdefault("XDG_CACHE_HOME", "/private/tmp/hvc-cache")

import cv2
import numpy as np

try:
    import mediapipe as mp
except ModuleNotFoundError:
    mp = None


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "workspace" / "dy_7671559890300685604"
SOURCE = PROJECT / "source.mp4"
BGM = PROJECT / "bgm_original.m4a"
MOTION_DIR = PROJECT / "motion"
MODEL = Path("/private/tmp/pose_landmarker_heavy.task")
RTMW_MODEL_DIR = Path("/private/tmp/hvc-rtmlib-cache/rtmlib/hub/checkpoints")
RTMW_DETECTOR = RTMW_MODEL_DIR / "yolox_m_8xb8-300e_humanart-c2c7a14a.onnx"
RTMW_POSE = RTMW_MODEL_DIR / "rtmw-dw-x-l_simcc-cocktail14_270e-384x288_20231122.onnx"
FPS = 30
FRAME_COUNT = 478
WIDTH = 1254
HEIGHT = 720
CUTS = (0, 362, 400, 478)
ROLES = ("female", "male")


@dataclass
class Candidate:
    landmarks: np.ndarray
    world: np.ndarray
    luma: float
    mean_visibility: float
    source: str

    @property
    def nose_x(self) -> float:
        return float(self.landmarks[0, 0])


def pose_options() -> mp.tasks.vision.PoseLandmarkerOptions:
    if mp is None:
        raise RuntimeError("重新检测动作需要安装 mediapipe；--render-existing 不需要")
    base = mp.tasks.BaseOptions(
        model_asset_path=str(MODEL),
        delegate=mp.tasks.BaseOptions.Delegate.CPU,
    )
    return mp.tasks.vision.PoseLandmarkerOptions(
        base_options=base,
        running_mode=mp.tasks.vision.RunningMode.IMAGE,
        num_poses=2,
        min_pose_detection_confidence=0.18,
        min_pose_presence_confidence=0.18,
        min_tracking_confidence=0.18,
        output_segmentation_masks=True,
    )


def detect_candidates(
    landmarker: mp.tasks.vision.PoseLandmarker,
    image: np.ndarray,
    source: str,
    x0: int = 0,
    y0: int = 0,
) -> list[Candidate]:
    crop_h, crop_w = image.shape[:2]
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    result = landmarker.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    candidates: list[Candidate] = []
    for index, pose in enumerate(result.pose_landmarks):
        landmarks = np.array([
            [
                (x0 + point.x * crop_w) / WIDTH,
                (y0 + point.y * crop_h) / HEIGHT,
                point.z * crop_w / WIDTH,
                point.visibility,
                point.presence,
            ]
            for point in pose
        ], dtype=np.float32)
        if index < len(result.pose_world_landmarks):
            world = np.array([
                [point.x, point.y, point.z] for point in result.pose_world_landmarks[index]
            ], dtype=np.float32)
        else:
            world = np.full((33, 3), np.nan, dtype=np.float32)

        luma = -1.0
        if index < len(result.segmentation_masks):
            mask = np.squeeze(result.segmentation_masks[index].numpy_view())
            ys, xs = np.where(mask > 0.55)
            if len(xs) > 50:
                luma = float(np.median(gray[ys, xs]))
        candidates.append(Candidate(
            landmarks=landmarks,
            world=world,
            luma=luma,
            mean_visibility=float(np.mean(landmarks[:, 3])),
            source=source,
        ))
    return candidates


def assign_full(frame_index: int, candidates: list[Candidate]) -> dict[str, Candidate]:
    if not candidates:
        return {}
    candidates = sorted(candidates, key=lambda item: item.nose_x)
    if len(candidates) >= 2:
        return {"male": candidates[0], "female": candidates[-1]}
    only = candidates[0]
    if frame_index < 362:
        return {"female": only}
    if frame_index < 400:
        return {"male" if only.nose_x < 0.55 else "female": only}
    if frame_index <= 427 and only.nose_x >= 0.56:
        return {"female": only}
    return {"male": only}


def best_male_crop(candidates: list[Candidate]) -> Candidate | None:
    dark = [
        candidate for candidate in candidates
        if 0 <= candidate.luma < 80 and candidate.mean_visibility >= 0.38
    ]
    if not dark:
        return None
    return min(dark, key=lambda item: (item.luma, item.nose_x))


def create_tracks() -> dict:
    shape = (FRAME_COUNT, 33, 5)
    tracks = {
        role: {
            "landmarks": np.full(shape, np.nan, dtype=np.float32),
            "world": np.full((FRAME_COUNT, 33, 3), np.nan, dtype=np.float32),
            "source": np.full(FRAME_COUNT, "missing", dtype=object),
            "score": np.zeros(FRAME_COUNT, dtype=np.float32),
        }
        for role in ROLES
    }
    return tracks


def store_candidate(tracks: dict, role: str, frame_index: int, candidate: Candidate) -> None:
    tracks[role]["landmarks"][frame_index] = candidate.landmarks
    tracks[role]["world"][frame_index] = candidate.world
    tracks[role]["source"][frame_index] = candidate.source
    tracks[role]["score"][frame_index] = candidate.mean_visibility


def detect_all() -> dict:
    if not MODEL.is_file():
        raise FileNotFoundError(f"姿态模型不存在: {MODEL}")
    tracks = create_tracks()
    capture = cv2.VideoCapture(str(SOURCE))
    if not capture.isOpened():
        raise RuntimeError(f"无法读取源视频: {SOURCE}")

    with mp.tasks.vision.PoseLandmarker.create_from_options(pose_options()) as landmarker:
        for frame_index in range(FRAME_COUNT):
            ok, frame = capture.read()
            if not ok:
                raise RuntimeError(f"源视频在第 {frame_index} 帧提前结束")

            full = detect_candidates(landmarker, frame, "model_full")
            for role, candidate in assign_full(frame_index, full).items():
                store_candidate(tracks, role, frame_index, candidate)

            if 75 <= frame_index < 362:
                crop = frame[:, :650]
                male = best_male_crop(detect_candidates(landmarker, crop, "model_male_crop"))
                if male is not None:
                    current_score = tracks["male"]["score"][frame_index]
                    if male.mean_visibility >= current_score - 0.08:
                        store_candidate(tracks, "male", frame_index, male)

            if frame_index % 30 == 0:
                female_ok = tracks["female"]["source"][frame_index] != "missing"
                male_ok = tracks["male"]["source"][frame_index] != "missing"
                print(f"detect F{frame_index:03d} female={female_ok} male={male_ok}", flush=True)
    capture.release()
    return tracks


def read_gray_range(start: int, end: int) -> dict[int, np.ndarray]:
    capture = cv2.VideoCapture(str(SOURCE))
    capture.set(cv2.CAP_PROP_POS_FRAMES, start)
    frames: dict[int, np.ndarray] = {}
    for frame_index in range(start, end + 1):
        ok, frame = capture.read()
        if not ok:
            break
        frames[frame_index] = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    capture.release()
    return frames


def transform_pose_with_flow(
    pose: np.ndarray,
    previous_gray: np.ndarray,
    next_gray: np.ndarray,
) -> np.ndarray:
    output = pose.copy()
    previous_points = np.column_stack((pose[:, 0] * WIDTH, pose[:, 1] * HEIGHT)).astype(np.float32)
    inside = (
        (previous_points[:, 0] >= 1) & (previous_points[:, 0] < WIDTH - 1) &
        (previous_points[:, 1] >= 1) & (previous_points[:, 1] < HEIGHT - 1) &
        (pose[:, 3] >= 0.20)
    )
    indexes = np.where(inside)[0]
    if len(indexes) < 2:
        output[:, 3] *= 0.98
        return output

    tracked, status, error = cv2.calcOpticalFlowPyrLK(
        previous_gray,
        next_gray,
        previous_points[indexes].reshape(-1, 1, 2),
        None,
        winSize=(35, 35),
        maxLevel=4,
        criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 35, 0.01),
    )
    tracked = tracked.reshape(-1, 2)
    status = status.reshape(-1).astype(bool)
    error = error.reshape(-1)
    backwards, back_status, _ = cv2.calcOpticalFlowPyrLK(
        next_gray,
        previous_gray,
        tracked.reshape(-1, 1, 2),
        None,
        winSize=(35, 35),
        maxLevel=4,
        criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 35, 0.01),
    )
    backwards = backwards.reshape(-1, 2)
    back_status = back_status.reshape(-1).astype(bool)
    round_trip = np.linalg.norm(backwards - previous_points[indexes], axis=1)
    displacement = np.linalg.norm(tracked - previous_points[indexes], axis=1)
    good = (
        status & back_status & np.isfinite(tracked).all(axis=1) &
        (error < 80) & (round_trip < 5.0) & (displacement < 90.0)
    )
    src = previous_points[indexes][good]
    dst = tracked[good]
    delta = np.median(dst - src, axis=0) if len(src) else np.zeros(2, dtype=np.float32)
    moved = previous_points + delta

    output[:, 0] = np.clip(moved[:, 0] / WIDTH, -0.5, 1.5)
    output[:, 1] = np.clip(moved[:, 1] / HEIGHT, -0.5, 1.5)
    output[:, 3] *= 0.995
    return output


def flow_fill(
    tracks: dict,
    role: str,
    anchor: int,
    target: int,
) -> None:
    start, end = sorted((anchor, target))
    gray = read_gray_range(start, end)
    step = 1 if target > anchor else -1
    current = tracks[role]["landmarks"][anchor].copy()
    current_world = tracks[role]["world"][anchor].copy()
    previous_frame = anchor
    for frame_index in range(anchor + step, target + step, step):
        if previous_frame not in gray or frame_index not in gray:
            break
        current = transform_pose_with_flow(current, gray[previous_frame], gray[frame_index])
        if tracks[role]["source"][frame_index] != "missing":
            current = tracks[role]["landmarks"][frame_index].copy()
            current_world = tracks[role]["world"][frame_index].copy()
        else:
            tracks[role]["landmarks"][frame_index] = current
            tracks[role]["world"][frame_index] = current_world
            tracks[role]["source"][frame_index] = "optical_flow"
            tracks[role]["score"][frame_index] = float(np.nanmean(current[:, 3]))
        previous_frame = frame_index


def prone_pose(center_x: float, center_y: float, base: np.ndarray) -> np.ndarray:
    offsets = {
        0: (0, 0), 1: (-8, -8), 2: (-10, -8), 3: (-12, -7),
        4: (8, -8), 5: (10, -8), 6: (12, -7), 7: (-19, 0), 8: (19, 0),
        9: (-6, 11), 10: (6, 11), 11: (-48, 30), 12: (48, 30),
        13: (-138, 42), 14: (138, 42), 15: (-228, 57), 16: (228, 57),
        17: (-237, 52), 18: (237, 52), 19: (-247, 57), 20: (247, 57),
        21: (-238, 64), 22: (238, 64), 23: (-32, 105), 24: (32, 105),
        25: (-48, 180), 26: (48, 180), 27: (-62, 255), 28: (62, 255),
        29: (-70, 270), 30: (70, 270), 31: (-82, 278), 32: (82, 278),
    }
    output = base.copy()
    for index, (dx, dy) in offsets.items():
        output[index, 0] = (center_x + dx) / WIDTH
        output[index, 1] = (center_y + dy) / HEIGHT
        output[index, 3] = 0.95 if index <= 22 else (0.35 if index <= 24 else 0.05)
        output[index, 4] = output[index, 3]
    return output


def apply_prone_female_fallback(tracks: dict) -> None:
    capture = cv2.VideoCapture(str(SOURCE))
    capture.set(cv2.CAP_PROP_POS_FRAMES, 421)
    anchor = tracks["female"]["landmarks"][420].copy()
    last_center = np.array([anchor[0, 0] * WIDTH, anchor[0, 1] * HEIGHT], dtype=np.float32)
    kernel = np.ones((7, 7), dtype=np.uint8)
    for frame_index in range(421, FRAME_COUNT):
        ok, frame = capture.read()
        if not ok:
            break
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        mask = (gray[500:720, 600:1050] < 72).astype(np.uint8) * 255
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        count, _, stats, centroids = cv2.connectedComponentsWithStats(mask)
        candidates = []
        for index in range(1, count):
            area = int(stats[index, cv2.CC_STAT_AREA])
            if area < 120:
                continue
            center = centroids[index] + np.array([600, 500], dtype=np.float64)
            distance = float(np.linalg.norm(center - last_center))
            candidates.append((area - distance * 12, center))
        if candidates:
            center = max(candidates, key=lambda item: item[0])[1].astype(np.float32)
            last_center = last_center * 0.35 + center * 0.65
        template = prone_pose(float(last_center[0]), float(last_center[1]), anchor)
        if frame_index < 430:
            amount = (frame_index - 420) / 10.0
            current = tracks["female"]["landmarks"][frame_index]
            template[:, :3] = current[:, :3] * (1 - amount) + template[:, :3] * amount
            template[:, 3:] = np.maximum(current[:, 3:] * (1 - amount), template[:, 3:] * amount)
        tracks["female"]["landmarks"][frame_index] = template
        tracks["female"]["world"][frame_index] = tracks["female"]["world"][420]
        tracks["female"]["source"][frame_index] = "prone_template"
        tracks["female"]["score"][frame_index] = 0.80
    capture.release()


RTMW_TO_MEDIAPIPE = {
    0: 0,
    1: 1, 2: 1, 3: 1,
    4: 2, 5: 2, 6: 2,
    7: 3, 8: 4,
    9: 71, 10: 77,
    11: 5, 12: 6,
    13: 7, 14: 8,
    15: 9, 16: 10,
    17: 111, 18: 132,
    19: 99, 20: 120,
    21: 95, 22: 116,
    23: 11, 24: 12,
    25: 13, 26: 14,
    27: 15, 28: 16,
    29: 19, 30: 22,
    31: 17, 32: 20,
}
RTMW_UPPER_BODY = np.array([0, 5, 6, 7, 8, 9, 10], dtype=np.int32)


def rtmw_to_mediapipe(keypoints: np.ndarray, scores: np.ndarray, base: np.ndarray) -> np.ndarray:
    output = base.copy()
    output[:, 2] = 0.0
    for target, source in RTMW_TO_MEDIAPIPE.items():
        output[target, 0] = np.clip(keypoints[source, 0] / WIDTH, -0.25, 1.25)
        output[target, 1] = np.clip(keypoints[source, 1] / HEIGHT, -0.25, 1.25)
        confidence = float(np.clip(scores[source] / 6.0, 0.05, 0.99))
        output[target, 3] = confidence
        output[target, 4] = confidence

    # Only the upper body is visible after the fall. Do not draw hallucinated legs.
    output[25:33, 3:] = 0.02
    return output


def map_clockwise_pose_to_source(keypoints: np.ndarray) -> np.ndarray:
    mapped = keypoints.copy()
    rotated_x = mapped[:, 0].copy()
    mapped[:, 0] = mapped[:, 1]
    mapped[:, 1] = HEIGHT - 1 - rotated_x
    return mapped


def rtmw_candidate_quality(
    keypoints: np.ndarray,
    scores: np.ndarray,
    previous_head: np.ndarray,
) -> float:
    head = keypoints[0]
    quality = float(np.mean(scores[RTMW_UPPER_BODY]))
    quality -= float(np.linalg.norm(head - previous_head)) / 180.0
    if not (560 <= head[0] <= WIDTH + 40 and 430 <= head[1] <= HEIGHT + 30):
        quality -= 8.0
    for start, end in ((5, 7), (7, 9), (6, 8), (8, 10), (5, 6)):
        length = float(np.linalg.norm(keypoints[start] - keypoints[end]))
        if length > 330:
            quality -= (length - 330) / 45.0
    return quality


def best_prone_auto_box(boxes: np.ndarray) -> np.ndarray | None:
    candidates = [
        box for box in boxes
        if box[1] >= 430 and box[2] >= 650 and box[2] - box[0] >= 220
        and (box[1] + box[3]) / 2 >= 560
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda box: (box[2] - box[0]) * (box[3] - box[1]))


def refine_prone_female_with_rtmw(tracks: dict) -> None:
    if not RTMW_DETECTOR.is_file() or not RTMW_POSE.is_file():
        raise FileNotFoundError(
            "RTMW 模型不存在；先通过本地代理下载到 " + str(RTMW_MODEL_DIR)
        )
    try:
        from rtmlib import Wholebody
    except ImportError as exc:
        raise RuntimeError("当前姿态环境未安装 rtmlib") from exc

    model = Wholebody(
        det=str(RTMW_DETECTOR),
        det_input_size=(640, 640),
        pose=str(RTMW_POSE),
        pose_input_size=(288, 384),
        backend="onnxruntime",
        device="cpu",
        to_openpose=False,
    )
    capture = cv2.VideoCapture(str(SOURCE))
    capture.set(cv2.CAP_PROP_POS_FRAMES, 421)
    previous_head = tracks["female"]["landmarks"][420, 0, :2] * np.array([WIDTH, HEIGHT])

    for frame_index in range(421, FRAME_COUNT):
        ok, frame = capture.read()
        if not ok:
            raise RuntimeError(f"RTMW 修复时源视频在第 {frame_index} 帧提前结束")

        boxes = model.det_model(frame)
        auto_box = best_prone_auto_box(boxes)
        candidates: list[tuple[float, np.ndarray, np.ndarray, str]] = []
        if auto_box is not None:
            keypoints, scores = model.pose_model(frame, bboxes=[auto_box])
            candidates.append((
                rtmw_candidate_quality(keypoints[0], scores[0], previous_head),
                keypoints[0], scores[0], "rtmw_auto",
            ))

        if auto_box is None:
            roi = [600, 460, WIDTH - 1, HEIGHT - 1]
            keypoints, scores = model.pose_model(frame, bboxes=[roi])
            candidates.append((
                rtmw_candidate_quality(keypoints[0], scores[0], previous_head),
                keypoints[0], scores[0], "rtmw_roi",
            ))

            rotated = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
            rotated_roi = [0, 600, HEIGHT - 461, WIDTH - 1]
            rotated_keypoints, rotated_scores = model.pose_model(rotated, bboxes=[rotated_roi])
            mapped = map_clockwise_pose_to_source(rotated_keypoints[0])
            candidates.append((
                rtmw_candidate_quality(mapped, rotated_scores[0], previous_head),
                mapped, rotated_scores[0], "rtmw_rotated_roi",
            ))

        _, keypoints, scores, source = max(candidates, key=lambda item: item[0])
        refined = rtmw_to_mediapipe(
            keypoints,
            scores,
            tracks["female"]["landmarks"][frame_index],
        )
        tracks["female"]["landmarks"][frame_index] = refined
        tracks["female"]["source"][frame_index] = source
        tracks["female"]["score"][frame_index] = float(
            np.clip(np.mean(scores[RTMW_UPPER_BODY]) / 6.0, 0.0, 1.0)
        )
        previous_head = keypoints[0].copy()
        if frame_index % 10 == 0 or frame_index == FRAME_COUNT - 1:
            print(f"RTMW F{frame_index:03d} source={source}", flush=True)
    capture.release()


def transform_pose_with_local_flow(
    pose: np.ndarray,
    previous_gray: np.ndarray,
    next_gray: np.ndarray,
) -> np.ndarray:
    output = pose.copy()
    previous_points = np.column_stack((pose[:, 0] * WIDTH, pose[:, 1] * HEIGHT)).astype(np.float32)
    inside = (
        (previous_points[:, 0] >= 1) & (previous_points[:, 0] < WIDTH - 1) &
        (previous_points[:, 1] >= 1) & (previous_points[:, 1] < HEIGHT - 1) &
        (pose[:, 3] >= 0.04)
    )
    indexes = np.where(inside)[0]
    if not len(indexes):
        return output

    tracked, status, error = cv2.calcOpticalFlowPyrLK(
        previous_gray,
        next_gray,
        previous_points[indexes].reshape(-1, 1, 2),
        None,
        winSize=(35, 35),
        maxLevel=4,
        criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 35, 0.01),
    )
    tracked = tracked.reshape(-1, 2)
    status = status.reshape(-1).astype(bool)
    error = error.reshape(-1)
    backwards, back_status, _ = cv2.calcOpticalFlowPyrLK(
        next_gray,
        previous_gray,
        tracked.reshape(-1, 1, 2),
        None,
        winSize=(35, 35),
        maxLevel=4,
        criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 35, 0.01),
    )
    backwards = backwards.reshape(-1, 2)
    back_status = back_status.reshape(-1).astype(bool)
    round_trip = np.linalg.norm(backwards - previous_points[indexes], axis=1)
    displacement = np.linalg.norm(tracked - previous_points[indexes], axis=1)
    good = (
        status & back_status & np.isfinite(tracked).all(axis=1) &
        (error < 65) & (round_trip < 4.0) & (displacement < 45.0)
    )
    delta = (
        np.median(tracked[good] - previous_points[indexes][good], axis=0)
        if np.any(good) else np.zeros(2, dtype=np.float32)
    )
    moved = previous_points + delta
    moved[indexes[good]] = tracked[good]
    output[:, 0] = np.clip(moved[:, 0] / WIDTH, -0.25, 1.25)
    output[:, 1] = np.clip(moved[:, 1] / HEIGHT, -0.25, 1.25)
    return output


def flow_lock_settled_prone_pose(tracks: dict, anchor: int = 458) -> None:
    start, end = 434, FRAME_COUNT - 1
    gray = read_gray_range(start, end)
    detected_transition = tracks["female"]["landmarks"][start:440].copy()
    anchor_pose = tracks["female"]["landmarks"][anchor].copy()
    anchor_world = tracks["female"]["world"][anchor].copy()
    anchor_score = float(tracks["female"]["score"][anchor])
    tracks["female"]["source"][anchor] = "rtmw_anchor"

    for step, target in ((-1, start), (1, end)):
        current = anchor_pose.copy()
        previous_frame = anchor
        for frame_index in range(anchor + step, target + step, step):
            current = transform_pose_with_local_flow(
                current,
                gray[previous_frame],
                gray[frame_index],
            )
            tracks["female"]["landmarks"][frame_index] = current
            tracks["female"]["world"][frame_index] = anchor_world
            tracks["female"]["source"][frame_index] = "rtmw_local_flow"
            tracks["female"]["score"][frame_index] = anchor_score
            previous_frame = frame_index

    for frame_index in range(start, 440):
        amount = (frame_index - 433) / 7.0
        detected = detected_transition[frame_index - start]
        flowed = tracks["female"]["landmarks"][frame_index]
        tracks["female"]["landmarks"][frame_index] = detected * (1 - amount) + flowed * amount
        tracks["female"]["source"][frame_index] = "rtmw_flow_blend"


def interpolate_missing(tracks: dict, role: str, active_start: int, active_end: int) -> None:
    landmarks = tracks[role]["landmarks"]
    world = tracks[role]["world"]
    sources = tracks[role]["source"]
    for shot_start, shot_end in zip(CUTS[:-1], CUTS[1:]):
        start = max(active_start, shot_start)
        end = min(active_end + 1, shot_end)
        if start >= end:
            continue
        valid = np.array([sources[index] != "missing" for index in range(start, end)])
        known = np.where(valid)[0] + start
        if not len(known):
            continue
        for frame_index in range(start, end):
            if sources[frame_index] != "missing":
                continue
            before = known[known < frame_index]
            after = known[known > frame_index]
            if not len(before) or not len(after):
                continue
            left, right = int(before[-1]), int(after[0])
            amount = (frame_index - left) / (right - left)
            landmarks[frame_index] = landmarks[left] * (1 - amount) + landmarks[right] * amount
            world[frame_index] = world[left] * (1 - amount) + world[right] * amount
            sources[frame_index] = "interpolated"
            tracks[role]["score"][frame_index] = (
                tracks[role]["score"][left] * (1 - amount) + tracks[role]["score"][right] * amount
            )


def repair_single_frame_outliers(tracks: dict, role: str, active_start: int, active_end: int) -> None:
    values = tracks[role]["landmarks"]
    sources = tracks[role]["source"]
    for shot_start, shot_end in zip(CUTS[:-1], CUTS[1:]):
        start = max(active_start + 1, shot_start + 1)
        end = min(active_end, shot_end - 1)
        for frame_index in range(start, end):
            if sources[frame_index] == "missing":
                continue
            expected = (values[frame_index - 1, :, :2] + values[frame_index + 1, :, :2]) / 2
            delta = np.linalg.norm(values[frame_index, :, :2] - expected, axis=1)
            low_confidence = values[frame_index, :, 3] < 0.55
            replace = (delta > 0.09) & low_confidence
            values[frame_index, replace, :2] = expected[replace]


def complete_tracks(tracks: dict, use_rtmw_prone: bool = True) -> None:
    male_known = np.where(tracks["male"]["source"] != "missing")[0]
    if not len(male_known):
        raise RuntimeError("没有检测到男角色")
    first_male = int(male_known[0])
    if first_male > 60:
        flow_fill(tracks, "male", first_male, 60)

    female_known = np.where(tracks["female"]["source"] != "missing")[0]
    if not len(female_known):
        raise RuntimeError("没有检测到女角色")
    last_female = int(female_known[female_known < 430][-1])
    if last_female < FRAME_COUNT - 1:
        flow_fill(tracks, "female", last_female, FRAME_COUNT - 1)
    apply_prone_female_fallback(tracks)
    if use_rtmw_prone:
        refine_prone_female_with_rtmw(tracks)
        flow_lock_settled_prone_pose(tracks)

    interpolate_missing(tracks, "female", 0, FRAME_COUNT - 1)
    interpolate_missing(tracks, "male", 60, FRAME_COUNT - 1)
    repair_single_frame_outliers(tracks, "female", 0, FRAME_COUNT - 1)
    repair_single_frame_outliers(tracks, "male", 60, FRAME_COUNT - 1)

    for role, active_start in (("female", 0), ("male", 60)):
        missing = [
            index for index in range(active_start, FRAME_COUNT)
            if tracks[role]["source"][index] == "missing"
        ]
        if missing:
            raise RuntimeError(f"{role} 动作轨仍有缺帧: {missing[:12]}")


LIMBS = (
    (11, 13, 0.12), (13, 15, 0.10), (12, 14, 0.12), (14, 16, 0.10),
    (23, 25, 0.16), (25, 27, 0.13), (24, 26, 0.16), (26, 28, 0.13),
    (15, 19, 0.06), (16, 20, 0.06), (27, 31, 0.08), (28, 32, 0.08),
)


def shade(color: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    return tuple(int(np.clip(channel * amount, 0, 255)) for channel in color)


def draw_mannequin(
    image: np.ndarray,
    pose: np.ndarray,
    color: tuple[int, int, int],
    opacity: float = 1.0,
    draw_head: bool = True,
) -> None:
    points = np.column_stack((pose[:, 0] * WIDTH, pose[:, 1] * HEIGHT)).astype(np.int32)
    shoulder_width = float(np.linalg.norm(points[11] - points[12]))
    hip_width = float(np.linalg.norm(points[23] - points[24]))
    scale = float(np.clip(max(shoulder_width, hip_width, 30.0), 25.0, 180.0))
    layer = image.copy()
    outline = shade(color, 0.48)
    highlight = shade(color, 1.12)

    torso = np.array([points[11], points[12], points[24], points[23]], dtype=np.int32)
    torso_edges = [np.linalg.norm(torso[index] - torso[(index + 1) % 4]) for index in range(4)]
    if max(torso_edges) < scale * 4:
        cv2.fillConvexPoly(layer, torso, color, cv2.LINE_AA)
        cv2.polylines(layer, [torso], True, outline, max(2, int(scale * 0.035)), cv2.LINE_AA)

    for start, end, width_ratio in LIMBS:
        if pose[start, 3] < 0.08 or pose[end, 3] < 0.08:
            continue
        if np.linalg.norm(points[start] - points[end]) > scale * 4:
            continue
        thickness = max(4, int(scale * width_ratio))
        cv2.line(layer, tuple(points[start]), tuple(points[end]), outline, thickness + 4, cv2.LINE_AA)
        cv2.line(layer, tuple(points[start]), tuple(points[end]), color, thickness, cv2.LINE_AA)
        offset = max(1, thickness // 5)
        cv2.line(
            layer,
            tuple(points[start] + (-offset, -offset)),
            tuple(points[end] + (-offset, -offset)),
            highlight,
            max(1, thickness // 5),
            cv2.LINE_AA,
        )

    joints = (11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28)
    for index in joints:
        if pose[index, 3] < 0.08:
            continue
        if not (-WIDTH * 0.2 <= points[index, 0] <= WIDTH * 1.2 and -HEIGHT * 0.2 <= points[index, 1] <= HEIGHT * 1.2):
            continue
        radius = max(3, int(scale * (0.07 if index in (11, 12, 23, 24) else 0.05)))
        cv2.circle(layer, tuple(points[index]), radius + 2, outline, -1, cv2.LINE_AA)
        cv2.circle(layer, tuple(points[index]), radius, color, -1, cv2.LINE_AA)
        cv2.circle(layer, tuple(points[index] - (radius // 3, radius // 3)), max(1, radius // 4), highlight, -1, cv2.LINE_AA)

    if draw_head:
        face_points = points[[0, 7, 8]]
        head_center = np.mean(face_points, axis=0).astype(np.int32)
        head_radius = max(7, int(scale * 0.20))
        if -WIDTH * 0.2 <= head_center[0] <= WIDTH * 1.2 and -HEIGHT * 0.2 <= head_center[1] <= HEIGHT * 1.2:
            cv2.circle(layer, tuple(head_center), head_radius + 3, outline, -1, cv2.LINE_AA)
            cv2.circle(layer, tuple(head_center), head_radius, color, -1, cv2.LINE_AA)
            cv2.circle(
                layer,
                tuple(head_center - (head_radius // 3, head_radius // 3)),
                max(2, head_radius // 5),
                highlight,
                -1,
                cv2.LINE_AA,
            )
    cv2.addWeighted(layer, opacity, image, 1.0 - opacity, 0, image)


def open_encoder(path: Path) -> subprocess.Popen:
    return subprocess.Popen([
        "ffmpeg", "-y", "-v", "error",
        "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{WIDTH}x{HEIGHT}",
        "-r", str(FPS), "-i", "-", "-an", "-frames:v", str(FRAME_COUNT),
        "-c:v", "libx264", "-preset", "fast", "-crf", "16", "-pix_fmt", "yuv420p",
        str(path),
    ], stdin=subprocess.PIPE)


def render_tracks(tracks: dict) -> None:
    MOTION_DIR.mkdir(parents=True, exist_ok=True)
    green_path = MOTION_DIR / "pose_control_green_478f.mp4"
    green_headless_path = MOTION_DIR / "pose_control_green_headless_478f.mp4"
    green_assetcolor_path = MOTION_DIR / "pose_control_green_assetcolor_headless_478f.mp4"
    control_overlay_path = MOTION_DIR / "pose_overlay_control_478f.mp4"
    headless_overlay_path = MOTION_DIR / "pose_overlay_headless_control_478f.mp4"
    overlay_path = MOTION_DIR / "pose_overlay_source_478f.mp4"
    green_encoder = open_encoder(green_path)
    green_headless_encoder = open_encoder(green_headless_path)
    green_assetcolor_encoder = open_encoder(green_assetcolor_path)
    control_overlay_encoder = open_encoder(control_overlay_path)
    headless_overlay_encoder = open_encoder(headless_overlay_path)
    overlay_encoder = open_encoder(overlay_path)
    capture = cv2.VideoCapture(str(SOURCE))
    colors = {"female": (45, 45, 220), "male": (232, 232, 232)}
    asset_colors = {"female": (235, 235, 235), "male": (45, 170, 225)}

    try:
        for frame_index in range(FRAME_COUNT):
            ok, source = capture.read()
            if not ok:
                raise RuntimeError(f"渲染时源视频在第 {frame_index} 帧提前结束")
            green = np.full((HEIGHT, WIDTH, 3), (42, 166, 61), dtype=np.uint8)
            cv2.rectangle(green, (0, int(HEIGHT * 0.78)), (WIDTH, HEIGHT), (36, 148, 52), -1)
            green_headless = green.copy()
            green_assetcolor = green.copy()
            overlay = source.copy()
            headless_overlay = source.copy()
            for role in ROLES:
                if tracks[role]["source"][frame_index] == "missing":
                    continue
                pose = tracks[role]["landmarks"][frame_index]
                draw_mannequin(green, pose, colors[role], opacity=1.0)
                draw_mannequin(
                    green_headless, pose, colors[role], opacity=1.0, draw_head=False
                )
                draw_mannequin(
                    green_assetcolor,
                    pose,
                    asset_colors[role],
                    opacity=1.0,
                    draw_head=False,
                )
                draw_mannequin(overlay, pose, colors[role], opacity=0.72)
                draw_mannequin(
                    headless_overlay, pose, colors[role], opacity=0.38, draw_head=False
                )
            control_overlay_encoder.stdin.write(overlay.tobytes())
            headless_overlay_encoder.stdin.write(headless_overlay.tobytes())
            cv2.putText(
                overlay, f"F{frame_index:04d}", (14, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA,
            )
            green_encoder.stdin.write(green.tobytes())
            green_headless_encoder.stdin.write(green_headless.tobytes())
            green_assetcolor_encoder.stdin.write(green_assetcolor.tobytes())
            overlay_encoder.stdin.write(overlay.tobytes())
            if frame_index % 60 == 0:
                print(f"render F{frame_index:03d}", flush=True)
    finally:
        capture.release()
        for encoder in (
            green_encoder,
            green_headless_encoder,
            green_assetcolor_encoder,
            control_overlay_encoder,
            headless_overlay_encoder,
            overlay_encoder,
        ):
            if encoder.stdin:
                encoder.stdin.close()
            code = encoder.wait()
            if code:
                raise RuntimeError(f"视频编码失败: {code}")

    preview = MOTION_DIR / "pose_control_green_with_bgm.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-i", str(green_path), "-i", str(BGM),
        "-map", "0:v:0", "-map", "1:a:0", "-frames:v", str(FRAME_COUNT),
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", str(preview),
    ], check=True)


def rounded_pose(values: np.ndarray) -> list[list[float]]:
    return [[round(float(value), 6) for value in row] for row in values]


def write_tracks(tracks: dict) -> None:
    frames = []
    for frame_index in range(FRAME_COUNT):
        row = {"frame": frame_index, "time": frame_index / FPS}
        for role in ROLES:
            present = tracks[role]["source"][frame_index] != "missing"
            row[role] = {
                "present": present,
                "source": str(tracks[role]["source"][frame_index]),
                "score": round(float(tracks[role]["score"][frame_index]), 4),
                "landmarks": rounded_pose(tracks[role]["landmarks"][frame_index]) if present else [],
                "world": rounded_pose(tracks[role]["world"][frame_index]) if present else [],
            }
        frames.append(row)

    counts = {
        role: {
            source: int(np.sum(tracks[role]["source"] == source))
            for source in sorted(set(tracks[role]["source"].tolist()))
        }
        for role in ROLES
    }
    rtmw_frames = sum(
        int(str(source).startswith("rtmw_"))
        for source in tracks["female"]["source"]
    )
    payload = {
        "schema_version": "1.0",
        "project_id": PROJECT.name,
        "source": "source.mp4",
        "fps": FPS,
        "frame_count": FRAME_COUNT,
        "duration": FRAME_COUNT / FPS,
        "cuts": list(CUTS),
        "role_mapping": {
            "female": {"control_color": "red", "target": "嫦娥", "asset": "assets/characters/change.png"},
            "male": {"control_color": "white", "target": "孙悟空", "asset": "assets/characters/wukong.png"},
        },
        "landmark_model": (
            "MediaPipe Pose Landmarker Heavy, 33 landmarks; "
            "RTMW Wholebody performance refinement for prone female frames"
            if rtmw_frames else "MediaPipe Pose Landmarker Heavy, 33 landmarks"
        ),
        "completion": (
            "role-locked detections with crop recovery, optical flow, cut-isolated interpolation, "
            "RTMW normal/rotated ROI selection, and local optical flow for the settled prone sequence"
            if rtmw_frames else
            "model detections with crop recovery, optical flow, and cut-isolated interpolation"
        ),
        "source_counts": counts,
        "frames": frames,
    }
    MOTION_DIR.mkdir(parents=True, exist_ok=True)
    (MOTION_DIR / "motion_tracks.json").write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    (PROJECT / "qc" / "pose_extraction.json").write_text(
        json.dumps({
            "fps": FPS,
            "frame_count": FRAME_COUNT,
            "cuts": list(CUTS),
            "active_frames": {"female": [0, 477], "male": [60, 477]},
            "source_counts": counts,
            "outputs": [
                "motion/motion_tracks.json",
                "motion/pose_control_green_478f.mp4",
                "motion/pose_control_green_headless_478f.mp4",
                "motion/pose_control_green_assetcolor_headless_478f.mp4",
                "motion/pose_control_green_with_bgm.mp4",
                "motion/pose_overlay_control_478f.mp4",
                "motion/pose_overlay_headless_control_478f.mp4",
                "motion/pose_overlay_source_478f.mp4",
            ],
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def load_existing_tracks() -> dict:
    path = MOTION_DIR / "motion_tracks.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if len(payload.get("frames", [])) != FRAME_COUNT:
        raise RuntimeError("现有动作轨帧数无效")
    tracks = create_tracks()
    for row in payload["frames"]:
        frame_index = int(row["frame"])
        for role in ROLES:
            item = row[role]
            if not item.get("present"):
                continue
            tracks[role]["landmarks"][frame_index] = np.asarray(item["landmarks"], dtype=np.float32)
            tracks[role]["world"][frame_index] = np.asarray(item["world"], dtype=np.float32)
            tracks[role]["source"][frame_index] = str(item["source"])
            tracks[role]["score"][frame_index] = float(item["score"])
    for role in ROLES:
        flow_frames = np.where(tracks[role]["source"] == "optical_flow")[0]
        tracks[role]["landmarks"][flow_frames] = np.nan
        tracks[role]["world"][flow_frames] = np.nan
        tracks[role]["source"][flow_frames] = "missing"
        tracks[role]["score"][flow_frames] = 0
    return tracks


def load_render_tracks() -> dict:
    path = MOTION_DIR / "motion_tracks.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if len(payload.get("frames", [])) != FRAME_COUNT:
        raise RuntimeError("现有动作轨帧数无效")
    tracks = create_tracks()
    for row in payload["frames"]:
        frame_index = int(row["frame"])
        for role in ROLES:
            item = row[role]
            if not item.get("present"):
                continue
            tracks[role]["landmarks"][frame_index] = np.asarray(item["landmarks"], dtype=np.float32)
            tracks[role]["world"][frame_index] = np.asarray(item["world"], dtype=np.float32)
            tracks[role]["source"][frame_index] = str(item["source"])
            tracks[role]["score"][frame_index] = float(item["score"])
    return tracks


def main() -> None:
    global MODEL
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, default=MODEL)
    parser.add_argument("--repair-existing", action="store_true")
    parser.add_argument("--render-existing", action="store_true")
    parser.add_argument("--skip-rtmw-prone", action="store_true")
    args = parser.parse_args()
    MODEL = args.model
    if args.render_existing:
        render_tracks(load_render_tracks())
        print(MOTION_DIR / "pose_control_green_headless_478f.mp4")
        return
    if mp is None:
        raise RuntimeError("重新检测动作需要安装 mediapipe")
    tracks = load_existing_tracks() if args.repair_existing else detect_all()
    complete_tracks(tracks, use_rtmw_prone=not args.skip_rtmw_prone)
    write_tracks(tracks)
    render_tracks(tracks)
    print(MOTION_DIR / "pose_control_green_with_bgm.mp4")


if __name__ == "__main__":
    main()

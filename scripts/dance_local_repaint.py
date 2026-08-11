#!/usr/bin/env python
"""Local Apple-Silicon pose repaint proof and frame renderer for the dance replica."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

import cv2
import numpy as np
import torch
from PIL import Image, ImageOps


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
PROJECT = ROOT / "workspace" / "dy_7671559890300685604"
MODEL_ROOT = PROJECT / "local_models"
OUTPUT_DIR = PROJECT / "local_proof"
TRACKS = PROJECT / "motion" / "motion_tracks.json"

BASE_MODEL = MODEL_ROOT / "dreamshaper-8"
BASE_MODEL_LCM = MODEL_ROOT / "dreamshaper-8-lcm" / "DreamShaper8_LCM.safetensors"
CONTROLNET = MODEL_ROOT / "controlnet-openpose"
IP_ADAPTER = MODEL_ROOT / "ip-adapter"

ASSETS = {
    "female": ROOT / "assets" / "characters" / "change.png",
    "male": ROOT / "assets" / "characters" / "wukong.png",
}
ROLE_NAMES = {"female": "Chang'e", "male": "Sun Wukong"}

WIDTH = 512
HEIGHT = 288
SOURCE_WIDTH = 1254
SOURCE_HEIGHT = 720
CROP_VERSION = 2
REFERENCE_VERSION = 3

POSE_EDGES = (
    (1, 2), (1, 5), (2, 3), (3, 4), (5, 6), (6, 7),
    (1, 8), (8, 9), (9, 10), (1, 11), (11, 12), (12, 13),
    (1, 0), (0, 14), (14, 16), (0, 15), (15, 17),
)
POSE_COLORS = (
    (255, 0, 0), (255, 85, 0), (255, 170, 0),
    (255, 255, 0), (170, 255, 0), (85, 255, 0), (0, 255, 0),
    (0, 255, 85), (0, 255, 170), (0, 255, 255),
    (0, 170, 255), (0, 85, 255), (0, 0, 255),
    (85, 0, 255), (170, 0, 255), (255, 0, 255),
    (255, 0, 170), (255, 0, 85),
)
MEDIAPIPE_TO_OPENPOSE = (0, None, 12, 14, 16, 11, 13, 15, 24, 26, 28, 23, 25, 27, 5, 2, 8, 7)

PROMPTS = {
    "female": (
        "single cinematic live-action Chang'e, exactly one woman, exact OpenPose body pose, same face and costume "
        "as reference, silver phoenix crown, pearl tassels, crescent forehead jewel, closed white embroidered "
        "ceremonial gown, floral shoulders, flowing sleeves, realistic human skin and silk, plain neutral background"
    ),
    "male": (
        "single cinematic live-action Sun Wukong, exactly one monkey man, exact OpenPose body pose, same monkey face "
        "as reference, golden circlet, golden-brown fur, fully closed mustard-yellow cross-collar tunic and trousers, "
        "orange waist apron with clear black tiger stripes, brown belt, bare feet, realistic fur and cloth, plain background"
    ),
}
NEGATIVE = (
    "3d, cgi, game art, low poly, plastic, doll, cartoon, anime, wrong costume, changed colors, extra people, duplicate, "
    "merged bodies, extra limbs, bad hands, red skin, horns, text, subtitle, watermark, logo, blurry, low detail, phone, watch"
    ", tiger animal, tiger face, tiger portrait, tiger painting, tiger mural, poster, bare chest, open shirt, black robe, "
    "black cloak, staff, pole, weapon, prop"
)


def configure_network() -> None:
    from hotvideocopy.config import CONFIG

    if CONFIG.proxy:
        os.environ.setdefault("HTTPS_PROXY", CONFIG.proxy)
        os.environ.setdefault("HTTP_PROXY", CONFIG.proxy)
    if CONFIG.hf_token:
        os.environ.setdefault("HF_TOKEN", CONFIG.hf_token)
    os.environ.setdefault("HF_HOME", str(MODEL_ROOT / ".hf-cache"))
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")


def load_tracks() -> list[dict]:
    payload = json.loads(TRACKS.read_text(encoding="utf-8"))
    frames = payload.get("frames") or []
    if len(frames) != 478:
        raise RuntimeError(f"动作轨帧数错误: {len(frames)}")
    return frames


def pose_image(frame_row: dict, role: str, width: int = WIDTH, height: int = HEIGHT) -> Image.Image:
    canvas = np.zeros((height, width, 3), dtype=np.uint8)
    role_row = frame_row[role]
    if not role_row.get("present"):
        return Image.fromarray(canvas)
    landmarks = np.asarray(role_row["landmarks"], dtype=np.float32)
    openpose = []
    for source_index in MEDIAPIPE_TO_OPENPOSE:
        if source_index is None:
            neck = (landmarks[11] + landmarks[12]) * 0.5
            neck[3] = min(landmarks[11, 3], landmarks[12, 3])
            openpose.append(neck)
        else:
            openpose.append(landmarks[source_index])
    openpose = np.asarray(openpose, dtype=np.float32)
    points = np.column_stack((openpose[:, 0] * width, openpose[:, 1] * height)).astype(np.int32)
    scale = max(2, int(np.clip(
        np.linalg.norm(points[2] - points[5]) * 0.08,
        2,
        7,
    )))
    for edge_index, (start, end) in enumerate(POSE_EDGES):
        if openpose[start, 3] < 0.08 or openpose[end, 3] < 0.08:
            continue
        if not all((
            -width // 3 <= points[start, 0] <= width * 4 // 3,
            -height // 3 <= points[start, 1] <= height * 4 // 3,
            -width // 3 <= points[end, 0] <= width * 4 // 3,
            -height // 3 <= points[end, 1] <= height * 4 // 3,
        )):
            continue
        color = POSE_COLORS[edge_index % len(POSE_COLORS)]
        cv2.line(canvas, tuple(points[start]), tuple(points[end]), color, scale, cv2.LINE_AA)
    for index, color in enumerate(POSE_COLORS):
        if openpose[index, 3] >= 0.08:
            cv2.circle(canvas, tuple(points[index]), scale + 1, color, -1, cv2.LINE_AA)
    return Image.fromarray(canvas)


def source_for_frame(frame_index: int, init_source: str) -> tuple[Path, int]:
    if init_source == "original":
        return PROJECT / "source.mp4", frame_index
    if frame_index < 167:
        return PROJECT / "gen" / "normalized_guanghan" / "s00_167f.mp4", frame_index
    if frame_index < 400:
        return PROJECT / "gen" / "normalized_guanghan" / "s01_233f.mp4", frame_index - 167
    return PROJECT / "gen" / "normalized_guanghan" / "s02_78f.mp4", frame_index - 400


def read_frame(frame_index: int, init_source: str) -> Image.Image:
    path, local_index = source_for_frame(frame_index, init_source)
    capture = cv2.VideoCapture(str(path))
    capture.set(cv2.CAP_PROP_POS_FRAMES, local_index)
    ok, frame = capture.read()
    capture.release()
    if not ok:
        raise RuntimeError(f"无法读取底稿帧: {path} #{local_index}")
    frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    return Image.fromarray(frame)


def role_crop_box(frame_row: dict, role: str, target_aspect: float) -> tuple[int, int, int, int]:
    landmarks = np.asarray(frame_row[role]["landmarks"], dtype=np.float32)
    body_indices = (0, 7, 8, 11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28)
    visible = landmarks[list(body_indices)]
    visible = visible[visible[:, 3] >= 0.08]
    if len(visible) < 5:
        return (0, 0, SOURCE_WIDTH, SOURCE_HEIGHT)

    x_min, y_min = visible[:, :2].min(axis=0)
    x_max, y_max = visible[:, :2].max(axis=0)
    body_height = max(0.18, float(y_max - y_min))
    horizontal_margin = body_height * (0.34 if role == "female" else 0.24)
    top_margin = body_height * (0.24 if role == "female" else 0.18)
    bottom_margin = body_height * 0.12
    left = (x_min - horizontal_margin) * SOURCE_WIDTH
    right = (x_max + horizontal_margin) * SOURCE_WIDTH
    top = (y_min - top_margin) * SOURCE_HEIGHT
    bottom = (y_max + bottom_margin) * SOURCE_HEIGHT

    center_x = (left + right) * 0.5
    center_y = (top + bottom) * 0.5
    crop_width = right - left
    crop_height = bottom - top
    if crop_width / crop_height < target_aspect:
        crop_width = crop_height * target_aspect
    else:
        crop_height = crop_width / target_aspect

    fit_scale = min(1.0, SOURCE_WIDTH / crop_width, SOURCE_HEIGHT / crop_height)
    width = crop_width * fit_scale
    height = crop_height * fit_scale
    left = center_x - width * 0.5
    top = center_y - height * 0.5
    left = min(max(0.0, left), SOURCE_WIDTH - width)
    top = min(max(0.0, top), SOURCE_HEIGHT - height)
    return (
        int(round(left)),
        int(round(top)),
        int(round(left + width)),
        int(round(top + height)),
    )


def erase_role(source: Image.Image, frame_row: dict, role: str) -> Image.Image:
    role_row = frame_row[role]
    if not role_row.get("present") or not role_row.get("landmarks"):
        return source
    landmarks = np.asarray(role_row["landmarks"], dtype=np.float32)
    indices = (0, 7, 8, 11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28)
    visible = [
        index for index in indices
        if landmarks[index, 3] >= 0.08
        and -0.1 <= landmarks[index, 0] <= 1.1
        and -0.1 <= landmarks[index, 1] <= 1.1
    ]
    if len(visible) < 5:
        return source
    points = np.array([
        [landmarks[index, 0] * source.width, landmarks[index, 1] * source.height]
        for index in visible
    ], dtype=np.int32)
    shoulders = np.array([
        landmarks[index, :2] * (source.width, source.height)
        for index in (11, 12)
    ], dtype=np.float32)
    radius = int(np.clip(np.linalg.norm(shoulders[0] - shoulders[1]) * 0.48, 32, 92))
    mask = np.zeros((source.height, source.width), dtype=np.uint8)
    hull = cv2.convexHull(points)
    cv2.fillConvexPoly(mask, hull, 255, cv2.LINE_AA)
    for point in points:
        cv2.circle(mask, tuple(point), radius, 255, -1, cv2.LINE_AA)
    kernel_size = radius * 2 + 1
    mask = cv2.dilate(
        mask,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size)),
    )
    repaired = cv2.inpaint(np.asarray(source), mask, 11, cv2.INPAINT_TELEA)
    return Image.fromarray(repaired)


def _expanded_pair(first: np.ndarray, second: np.ndarray, scale: float) -> tuple[np.ndarray, np.ndarray]:
    center = (first + second) * 0.5
    return center + (first - center) * scale, center + (second - center) * scale


def _tint_masked_region(
    image: np.ndarray,
    mask: np.ndarray,
    target_rgb: tuple[int, int, int],
    opacity: float,
) -> np.ndarray:
    luma = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY).astype(np.float32) / 255.0
    target = np.asarray(target_rgb, dtype=np.float32)[None, None, :]
    tinted = target * (0.46 + luma[:, :, None] * 0.82)
    alpha = cv2.GaussianBlur(mask, (0, 0), 7.0).astype(np.float32) / 255.0
    alpha = np.clip(alpha * opacity, 0.0, 1.0)[:, :, None]
    return np.clip(image * (1.0 - alpha) + tinted * alpha, 0, 255).astype(np.uint8)


def apply_costume_hint(source: Image.Image, frame_row: dict, role: str) -> Image.Image:
    """Place pose-aware Wukong colors/textures before diffusion repainting."""
    if role != "male" or not frame_row[role].get("present"):
        return source
    landmarks = np.asarray(frame_row[role]["landmarks"], dtype=np.float32)
    points = np.column_stack((
        landmarks[:, 0] * source.width,
        landmarks[:, 1] * source.height,
    )).astype(np.float32)
    required = (11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28)
    if any(landmarks[index, 3] < 0.08 for index in required):
        return source

    image = np.asarray(source).astype(np.float32)
    shoulder_width = float(np.linalg.norm(points[11] - points[12]))
    radius = max(18, int(round(shoulder_width * 0.24)))
    clothing_mask = np.zeros((source.height, source.width), dtype=np.uint8)

    shoulder_pair = _expanded_pair(points[11], points[12], 1.18)
    hip_pair = _expanded_pair(points[23], points[24], 1.25)
    top = sorted(shoulder_pair, key=lambda point: point[0])
    bottom = sorted(hip_pair, key=lambda point: point[0])
    torso = np.asarray((top[0], top[1], bottom[1], bottom[0]), dtype=np.int32)
    cv2.fillConvexPoly(clothing_mask, torso, 255, cv2.LINE_AA)
    for chain in ((11, 13, 15), (12, 14, 16), (23, 25, 27), (24, 26, 28)):
        cv2.line(clothing_mask, tuple(points[chain[0]].astype(int)), tuple(points[chain[1]].astype(int)), 255, radius * 2, cv2.LINE_AA)
        cv2.line(clothing_mask, tuple(points[chain[1]].astype(int)), tuple(points[chain[2]].astype(int)), 255, radius * 2, cv2.LINE_AA)
    image = _tint_masked_region(image, clothing_mask, (198, 145, 35), 0.82)

    asset = np.asarray(Image.open(ASSETS["male"]).convert("RGB"))
    shirt = asset[330:710, 405:695]
    shirt_source_quad = np.float32([
        [0, 0],
        [shirt.shape[1] - 1, 0],
        [shirt.shape[1] - 1, shirt.shape[0] - 1],
        [0, shirt.shape[0] - 1],
    ])
    shirt_top = sorted(_expanded_pair(points[11], points[12], 1.18), key=lambda point: point[0])
    shirt_bottom = sorted(_expanded_pair(points[23], points[24], 1.42), key=lambda point: point[0])
    shirt_target_quad = np.float32((
        shirt_top[0], shirt_top[1], shirt_bottom[1], shirt_bottom[0],
    ))
    shirt_transform = cv2.getPerspectiveTransform(shirt_source_quad, shirt_target_quad)
    warped_shirt = cv2.warpPerspective(
        shirt,
        shirt_transform,
        (source.width, source.height),
        flags=cv2.INTER_LANCZOS4,
        borderMode=cv2.BORDER_CONSTANT,
    )
    shirt_mask = cv2.warpPerspective(
        np.full(shirt.shape[:2], 255, dtype=np.uint8),
        shirt_transform,
        (source.width, source.height),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
    )
    shirt_alpha = cv2.GaussianBlur(shirt_mask, (0, 0), 5.0).astype(np.float32) / 255.0
    shirt_alpha = np.clip(shirt_alpha * 0.88, 0.0, 1.0)[:, :, None]
    image = np.clip(
        image * (1.0 - shirt_alpha) + warped_shirt.astype(np.float32) * shirt_alpha,
        0,
        255,
    )

    apron = asset[680:1130, 245:735]
    source_quad = np.float32([
        [0, 0],
        [apron.shape[1] - 1, 0],
        [apron.shape[1] - 1, apron.shape[0] - 1],
        [0, apron.shape[0] - 1],
    ])
    upper = list(_expanded_pair(points[23], points[24], 1.95))
    lower_left = points[23] * 0.18 + points[25] * 0.82
    lower_right = points[24] * 0.18 + points[26] * 0.82
    lower = list(_expanded_pair(lower_left, lower_right, 1.72))
    upper = sorted(upper, key=lambda point: point[0])
    lower = sorted(lower, key=lambda point: point[0])
    torso_height = float(np.mean([
        np.linalg.norm(points[11] - points[23]),
        np.linalg.norm(points[12] - points[24]),
    ]))
    upper = [point - np.array((0.0, torso_height * 0.18), dtype=np.float32) for point in upper]
    target_quad = np.float32((upper[0], upper[1], lower[1], lower[0]))
    transform = cv2.getPerspectiveTransform(source_quad, target_quad)
    warped = cv2.warpPerspective(
        apron,
        transform,
        (source.width, source.height),
        flags=cv2.INTER_LANCZOS4,
        borderMode=cv2.BORDER_CONSTANT,
    )
    source_mask = np.full(apron.shape[:2], 255, dtype=np.uint8)
    apron_mask = cv2.warpPerspective(
        source_mask,
        transform,
        (source.width, source.height),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
    )
    alpha = cv2.GaussianBlur(apron_mask, (0, 0), 5.0).astype(np.float32) / 255.0
    alpha = np.clip(alpha * 0.88, 0.0, 1.0)[:, :, None]
    image = np.clip(image * (1.0 - alpha) + warped.astype(np.float32) * alpha, 0, 255)
    return Image.fromarray(image.astype(np.uint8))


def apron_region_mask(
    frame_row: dict,
    crop_box: tuple[int, int, int, int] | None,
    render_width: int,
    render_height: int,
) -> np.ndarray:
    landmarks = np.asarray(frame_row["male"]["landmarks"], dtype=np.float32)
    points = np.column_stack((
        landmarks[:, 0] * SOURCE_WIDTH,
        landmarks[:, 1] * SOURCE_HEIGHT,
    )).astype(np.float32)
    upper = sorted(_expanded_pair(points[23], points[24], 1.95), key=lambda point: point[0])
    lower_left = points[23] * 0.18 + points[25] * 0.82
    lower_right = points[24] * 0.18 + points[26] * 0.82
    lower = sorted(_expanded_pair(lower_left, lower_right, 1.72), key=lambda point: point[0])
    torso_height = float(np.mean([
        np.linalg.norm(points[11] - points[23]),
        np.linalg.norm(points[12] - points[24]),
    ]))
    upper = [point - np.array((0.0, torso_height * 0.18), dtype=np.float32) for point in upper]
    target_quad = np.asarray((upper[0], upper[1], lower[1], lower[0]), dtype=np.int32)
    mask = np.zeros((SOURCE_HEIGHT, SOURCE_WIDTH), dtype=np.uint8)
    cv2.fillConvexPoly(mask, target_quad, 255, cv2.LINE_AA)
    if crop_box is not None:
        left, top, right, bottom = crop_box
        mask = mask[top:bottom, left:right]
    return cv2.resize(mask, (render_width, render_height), interpolation=cv2.INTER_LINEAR)


def torso_region_mask(
    frame_row: dict,
    crop_box: tuple[int, int, int, int] | None,
    render_width: int,
    render_height: int,
) -> np.ndarray:
    landmarks = np.asarray(frame_row["male"]["landmarks"], dtype=np.float32)
    points = np.column_stack((
        landmarks[:, 0] * SOURCE_WIDTH,
        landmarks[:, 1] * SOURCE_HEIGHT,
    )).astype(np.float32)
    upper = sorted(_expanded_pair(points[11], points[12], 1.18), key=lambda point: point[0])
    lower = sorted(_expanded_pair(points[23], points[24], 1.42), key=lambda point: point[0])
    polygon = np.asarray((upper[0], upper[1], lower[1], lower[0]), dtype=np.int32)
    mask = np.zeros((SOURCE_HEIGHT, SOURCE_WIDTH), dtype=np.uint8)
    cv2.fillConvexPoly(mask, polygon, 255, cv2.LINE_AA)
    if crop_box is not None:
        left, top, right, bottom = crop_box
        mask = mask[top:bottom, left:right]
    return cv2.resize(mask, (render_width, render_height), interpolation=cv2.INTER_LINEAR)


def lock_apron_texture(
    output: Image.Image,
    init: Image.Image,
    frame_row: dict,
    crop_box: tuple[int, int, int, int] | None,
) -> Image.Image:
    apron_mask = apron_region_mask(frame_row, crop_box, output.width, output.height)
    torso_mask = torso_region_mask(frame_row, crop_box, output.width, output.height)
    apron_alpha = cv2.GaussianBlur(apron_mask, (0, 0), 3.2).astype(np.float32) / 255.0
    torso_alpha = cv2.GaussianBlur(torso_mask, (0, 0), 3.2).astype(np.float32) / 255.0
    alpha = np.maximum(apron_alpha * 0.68, torso_alpha * 0.52)
    alpha = np.clip(alpha, 0.0, 0.68)[:, :, None]
    base = np.asarray(output).astype(np.float32)
    detail = np.asarray(init).astype(np.float32)
    selected = np.maximum(apron_mask, torso_mask) >= 128
    if np.any(selected):
        base_luma = cv2.cvtColor(base.astype(np.uint8), cv2.COLOR_RGB2GRAY)
        detail_luma = cv2.cvtColor(detail.astype(np.uint8), cv2.COLOR_RGB2GRAY)
        gain = float(np.mean(base_luma[selected]) / max(1.0, np.mean(detail_luma[selected])))
        detail *= float(np.clip(gain, 0.72, 1.28))
    merged = np.clip(base * (1.0 - alpha) + detail * alpha, 0, 255).astype(np.uint8)
    return Image.fromarray(merged)


def frame_inputs(
    frame_index: int,
    frame_row: dict,
    role: str,
    role_crop: bool,
    render_width: int,
    render_height: int,
    erase_other: bool,
    erase_target: bool,
    init_source: str,
    costume_hint: bool,
) -> tuple[Image.Image, Image.Image, tuple[int, int, int, int] | None]:
    source = read_frame(frame_index, init_source)
    control = pose_image(frame_row, role, source.width, source.height)
    crop_box = None
    if erase_other:
        other_role = "male" if role == "female" else "female"
        source = erase_role(source, frame_row, other_role)
    if erase_target:
        source = erase_role(source, frame_row, role)
    if costume_hint:
        source = apply_costume_hint(source, frame_row, role)
    if role_crop:
        crop_box = role_crop_box(frame_row, role, render_width / render_height)
        source = source.crop(crop_box)
        control = control.crop(crop_box)
    return (
        source.resize((render_width, render_height), Image.Resampling.LANCZOS),
        control.resize((render_width, render_height), Image.Resampling.LANCZOS),
        crop_box,
    )


def reference_image(role: str) -> Image.Image:
    source = Image.open(ASSETS[role]).convert("RGB")
    if role == "male":
        # A multi-panel or full-body reference is interpreted as extra people
        # and also leaks the phone pose. Keep IP-Adapter identity-only; the
        # pose-aware init image supplies the exact costume pixels separately.
        head = source.crop((315, 35, 760, 380))
        fitted = ImageOps.contain(head, (920, 920), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (1024, 1024), (35, 36, 40))
        canvas.paste(fitted, ((canvas.width - fitted.width) // 2, (canvas.height - fitted.height) // 2))
        return canvas
    fitted = ImageOps.contain(source, (1024, 1024), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (1024, 1024), (35, 36, 40))
    offset = ((canvas.width - fitted.width) // 2, (canvas.height - fitted.height) // 2)
    canvas.paste(fitted, offset)
    return canvas


def build_pipeline(ip_scale: float, model: str):
    configure_network()
    from diffusers import (
        ControlNetModel,
        DPMSolverMultistepScheduler,
        LCMScheduler,
        StableDiffusionControlNetImg2ImgPipeline,
    )

    selected_model = BASE_MODEL if model == "standard" else BASE_MODEL_LCM
    missing = [path for path in (selected_model, CONTROLNET, IP_ADAPTER) if not path.exists()]
    if missing:
        raise FileNotFoundError(missing[0])
    dtype = torch.float16
    controlnet = ControlNetModel.from_pretrained(
        str(CONTROLNET),
        torch_dtype=dtype,
        variant="fp16",
        use_safetensors=True,
        local_files_only=True,
    )
    common = {
        "controlnet": controlnet,
        "torch_dtype": dtype,
        "safety_checker": None,
        "feature_extractor": None,
        "requires_safety_checker": False,
    }
    if model == "standard":
        pipe = StableDiffusionControlNetImg2ImgPipeline.from_pretrained(
            str(BASE_MODEL),
            variant="fp16",
            local_files_only=True,
            **common,
        )
        pipe.scheduler = DPMSolverMultistepScheduler.from_config(
            pipe.scheduler.config,
            algorithm_type="dpmsolver++",
            use_karras_sigmas=True,
        )
    else:
        pipe = StableDiffusionControlNetImg2ImgPipeline.from_single_file(
            str(BASE_MODEL_LCM),
            local_files_only=False,
            **common,
        )
        pipe.scheduler = LCMScheduler.from_config(pipe.scheduler.config)
    pipe.load_ip_adapter(
        str(IP_ADAPTER),
        subfolder="models",
        weight_name="ip-adapter-plus_sd15.safetensors",
        image_encoder_folder="models/image_encoder",
        local_files_only=True,
    )
    pipe.set_ip_adapter_scale(ip_scale)
    # Attention slicing replaces the IP-Adapter processor in diffusers 0.37.
    pipe.vae.enable_slicing()
    pipe.to("mps")
    return pipe


def render(
    pipe,
    frame_index: int,
    role: str,
    seed: int,
    strength: float,
    ip_scale: float,
    control_scale: float,
    steps: int,
    guidance: float,
    model: str,
    role_crop: bool,
    render_width: int,
    render_height: int,
    erase_other: bool,
    erase_target: bool,
    init_source: str,
    costume_hint: bool,
    lock_apron: bool,
) -> Path:
    tracks = load_tracks()
    init, control, crop_box = frame_inputs(
        frame_index,
        tracks[frame_index],
        role,
        role_crop,
        render_width,
        render_height,
        erase_other,
        erase_target,
        init_source,
        costume_hint,
    )
    reference = reference_image(role)
    generator = torch.Generator(device="cpu").manual_seed(seed)
    start = time.monotonic()
    with torch.inference_mode():
        output = pipe(
            prompt=PROMPTS[role],
            negative_prompt=NEGATIVE,
            image=init,
            control_image=control,
            ip_adapter_image=reference,
            strength=strength,
            num_inference_steps=steps,
            guidance_scale=guidance,
            controlnet_conditioning_scale=control_scale,
            generator=generator,
        ).images[0]
    raw_output = output
    if lock_apron and role == "male" and costume_hint:
        output = lock_apron_texture(output, init, tracks[frame_index], crop_box)
    elapsed = time.monotonic() - start
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stem = (
        f"f{frame_index:03d}_{role}_s{strength:.2f}_ip{ip_scale:.2f}_"
        f"pose{control_scale:.2f}_n{steps}_op18_refv{REFERENCE_VERSION}_"
        f"cropv{CROP_VERSION}_{render_width}x{render_height}_"
        f"erase{int(erase_other)}_target{int(erase_target)}_"
        f"hint{int(costume_hint)}_lock{int(lock_apron)}_"
        f"{init_source}_seed{seed}"
    )
    output_path = OUTPUT_DIR / f"{stem}.png"
    pose_path = OUTPUT_DIR / f"{stem}_pose.png"
    init_path = OUTPUT_DIR / f"{stem}_init.png"
    output.save(output_path)
    if output is not raw_output:
        raw_output.save(OUTPUT_DIR / f"{stem}_raw.png")
    control.save(pose_path)
    init.save(init_path)
    (OUTPUT_DIR / f"{stem}.json").write_text(json.dumps({
        "frame": frame_index,
        "role": role,
        "role_name": ROLE_NAMES[role],
        "seed": seed,
        "strength": strength,
        "steps": steps,
        "ip_adapter_scale": ip_scale,
        "controlnet_conditioning_scale": control_scale,
        "guidance_scale": guidance,
        "pose_format": "openpose_18_rgb",
        "width": render_width,
        "height": render_height,
        "role_crop": role_crop,
        "erase_other": erase_other,
        "erase_target": erase_target,
        "init_source": init_source,
        "costume_hint": costume_hint,
        "lock_apron": lock_apron,
        "crop_box": crop_box,
        "crop_version": CROP_VERSION,
        "reference_version": REFERENCE_VERSION,
        "seconds": elapsed,
        "base_model": str((BASE_MODEL if model == "standard" else BASE_MODEL_LCM).relative_to(ROOT)),
        "controlnet": str(CONTROLNET.relative_to(ROOT)),
        "ip_adapter": str(IP_ADAPTER.relative_to(ROOT)),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output_path), "seconds": round(elapsed, 2)}, ensure_ascii=False))
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frame", type=int, choices=range(478))
    parser.add_argument("--frames", help="逗号分隔的帧号；与 --frame 二选一")
    parser.add_argument("--role", choices=("female", "male"), default="female")
    parser.add_argument("--model", choices=("standard", "lcm"), default="standard")
    parser.add_argument("--role-crop", action="store_true")
    parser.add_argument("--erase-other", action="store_true")
    parser.add_argument("--erase-target", action="store_true")
    parser.add_argument("--costume-hint", action="store_true")
    parser.add_argument("--lock-apron", action="store_true")
    parser.add_argument("--init-source", choices=("original", "guanghan"), default="original")
    parser.add_argument("--width", type=int, default=WIDTH)
    parser.add_argument("--height", type=int, default=HEIGHT)
    parser.add_argument("--seed", type=int, default=767155)
    parser.add_argument("--strength", type=float, default=0.68)
    parser.add_argument("--ip-scale", type=float, default=0.45)
    parser.add_argument("--control-scale", type=float, default=1.35)
    parser.add_argument("--steps", type=int, default=20)
    parser.add_argument("--guidance", type=float, default=6.0)
    args = parser.parse_args()
    if args.frame is not None and args.frames:
        parser.error("--frame 与 --frames 不能同时使用")
    if args.frames:
        try:
            frame_indices = [int(value.strip()) for value in args.frames.split(",") if value.strip()]
        except ValueError:
            parser.error("--frames 必须是逗号分隔的整数")
        if not frame_indices or any(index not in range(478) for index in frame_indices):
            parser.error("--frames 中的帧号必须在 0 到 477 之间")
    else:
        frame_indices = [args.frame if args.frame is not None else 0]
    if not 0.20 <= args.strength <= 0.90:
        parser.error("--strength 必须在 0.20 到 0.90 之间")
    if not 0.0 <= args.ip_scale <= 1.5:
        parser.error("--ip-scale 必须在 0.0 到 1.5 之间")
    if not 0.0 <= args.control_scale <= 2.0:
        parser.error("--control-scale 必须在 0.0 到 2.0 之间")
    if not 4 <= args.steps <= 30:
        parser.error("--steps 必须在 4 到 30 之间")
    if args.width % 8 or args.height % 8 or min(args.width, args.height) < 256:
        parser.error("--width 和 --height 必须是 8 的倍数且不小于 256")
    pipe = build_pipeline(args.ip_scale, args.model)
    for frame_index in frame_indices:
        render(
            pipe,
            frame_index,
            args.role,
            args.seed,
            args.strength,
            args.ip_scale,
            args.control_scale,
            args.steps,
            args.guidance,
            args.model,
            args.role_crop,
            args.width,
            args.height,
            args.erase_other,
            args.erase_target,
            args.init_source,
            args.costume_hint,
            args.lock_apron,
        )


if __name__ == "__main__":
    main()

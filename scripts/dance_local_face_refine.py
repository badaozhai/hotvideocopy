#!/usr/bin/env python
"""Locally refine a generated dance frame's face from the character asset."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

import numpy as np
import torch
from PIL import Image, ImageDraw, ImageFilter


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
PROJECT = ROOT / "workspace" / "dy_7671559890300685604"
MODEL_ROOT = PROJECT / "local_models"
BASE_MODEL = MODEL_ROOT / "dreamshaper-8"
IP_ADAPTER = MODEL_ROOT / "ip-adapter"
TRACKS = PROJECT / "motion" / "motion_tracks.json"
OUTPUT_DIR = PROJECT / "local_face_proof"

ASSETS = {
    "female": ROOT / "assets" / "characters" / "change.png",
    "male": ROOT / "assets" / "characters" / "wukong.png",
}

PROMPTS = {
    "female": (
        "close portrait of the exact same Chang'e woman from reference, same face, natural human eyes, nose and lips, "
        "black updo, silver forehead crescent and pearl jewelry, photorealistic live action, detailed natural skin"
    ),
    "male": (
        "close portrait of the exact same Sun Wukong from reference, same golden-brown monkey face, light muzzle, "
        "golden headband, realistic detailed fur and skin, photorealistic live action"
    ),
}
NEGATIVE = (
    "deformed face, nonhuman woman, asymmetrical eyes, crossed eyes, extra eyes, extra mouth, wax skin, plastic, doll, "
    "cgi, low poly, cartoon, anime, blurry, low detail, text, subtitle, watermark, logo"
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


def build_pipeline(ip_scale: float):
    configure_network()
    from diffusers import DPMSolverMultistepScheduler, StableDiffusionImg2ImgPipeline

    pipe = StableDiffusionImg2ImgPipeline.from_pretrained(
        str(BASE_MODEL),
        torch_dtype=torch.float16,
        variant="fp16",
        safety_checker=None,
        feature_extractor=None,
        requires_safety_checker=False,
        local_files_only=True,
    )
    pipe.scheduler = DPMSolverMultistepScheduler.from_config(
        pipe.scheduler.config,
        algorithm_type="dpmsolver++",
        use_karras_sigmas=True,
    )
    pipe.load_ip_adapter(
        str(IP_ADAPTER),
        subfolder="models",
        weight_name="ip-adapter-plus_sd15.safetensors",
        image_encoder_folder="models/image_encoder",
        local_files_only=True,
    )
    pipe.set_ip_adapter_scale(ip_scale)
    pipe.vae.enable_slicing()
    pipe.to("mps")
    return pipe


def load_frame_row(frame_index: int) -> dict:
    payload = json.loads(TRACKS.read_text(encoding="utf-8"))
    return payload["frames"][frame_index]


def face_reference(role: str) -> Image.Image:
    source = Image.open(ASSETS[role]).convert("RGB")
    if role == "female":
        bounds = (0.26, 0.09, 0.74, 0.43)
    else:
        bounds = (0.25, 0.04, 0.76, 0.36)
    box = (
        int(source.width * bounds[0]),
        int(source.height * bounds[1]),
        int(source.width * bounds[2]),
        int(source.height * bounds[3]),
    )
    crop = source.crop(box)
    side = max(crop.size)
    canvas = Image.new("RGB", (side, side), (35, 36, 40))
    canvas.paste(crop, ((side - crop.width) // 2, (side - crop.height) // 2))
    return canvas.resize((512, 512), Image.Resampling.LANCZOS)


def head_box(input_path: Path, frame_index: int, role: str) -> tuple[int, int, int, int]:
    metadata_path = input_path.with_suffix(".json")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    crop_box = metadata.get("crop_box")
    if not crop_box:
        raise RuntimeError("输入必须是 --role-crop 生成的角色图")
    image = Image.open(input_path)
    landmarks = np.asarray(load_frame_row(frame_index)[role]["landmarks"], dtype=np.float32)
    left, top, right, bottom = crop_box

    def project(index: int) -> np.ndarray:
        point = landmarks[index]
        return np.array([
            (point[0] * 1254 - left) / (right - left) * image.width,
            (point[1] * 720 - top) / (bottom - top) * image.height,
        ])

    nose = project(0)
    shoulders = np.linalg.norm(project(11) - project(12))
    ears = np.linalg.norm(project(7) - project(8))
    side = int(round(max(128.0, shoulders * 1.45, ears * 2.4)))
    center_x = float(nose[0])
    center_y = float(nose[1] - side * 0.04)
    x0 = int(round(center_x - side / 2))
    y0 = int(round(center_y - side / 2))
    x0 = min(max(0, x0), max(0, image.width - side))
    y0 = min(max(0, y0), max(0, image.height - side))
    side = min(side, image.width - x0, image.height - y0)
    return (x0, y0, x0 + side, y0 + side)


def composite_face(base: Image.Image, refined: Image.Image, box: tuple[int, int, int, int]) -> Image.Image:
    width = box[2] - box[0]
    height = box[3] - box[1]
    refined = refined.resize((width, height), Image.Resampling.LANCZOS)
    mask = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse(
        (int(width * 0.24), int(height * 0.20), int(width * 0.76), int(height * 0.82)),
        fill=255,
    )
    mask = mask.filter(ImageFilter.GaussianBlur(max(4, width // 28)))
    result = base.copy()
    result.paste(refined, box[:2], mask)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--frame", type=int, required=True, choices=range(478))
    parser.add_argument("--role", choices=("female", "male"), required=True)
    parser.add_argument("--seed", type=int, default=767155)
    parser.add_argument("--strength", type=float, default=0.38)
    parser.add_argument("--ip-scale", type=float, default=0.95)
    parser.add_argument("--steps", type=int, default=20)
    args = parser.parse_args()

    source = Image.open(args.input).convert("RGB")
    box = head_box(args.input, args.frame, args.role)
    head = source.crop(box).resize((512, 512), Image.Resampling.LANCZOS)
    reference = face_reference(args.role)
    pipe = build_pipeline(args.ip_scale)
    generator = torch.Generator(device="cpu").manual_seed(args.seed)
    started = time.monotonic()
    with torch.inference_mode():
        refined = pipe(
            prompt=PROMPTS[args.role],
            negative_prompt=NEGATIVE,
            image=head,
            ip_adapter_image=reference,
            strength=args.strength,
            num_inference_steps=args.steps,
            guidance_scale=6.0,
            generator=generator,
        ).images[0]

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"{args.input.stem}_face_{args.role}_s{args.strength:.2f}_ip{args.ip_scale:.2f}"
    output_path = OUTPUT_DIR / f"{stem}.png"
    input_path = OUTPUT_DIR / f"{stem}_input.png"
    reference_path = OUTPUT_DIR / f"{stem}_reference.png"
    composite_path = OUTPUT_DIR / f"{stem}_composite.png"
    refined.save(output_path)
    head.save(input_path)
    reference.save(reference_path)
    composite_face(source, refined, box).save(composite_path)
    print(json.dumps({
        "output": str(output_path),
        "composite": str(composite_path),
        "head_box": box,
        "seconds": round(time.monotonic() - started, 2),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()

#!/usr/bin/env python
"""Apply local InsightFace identity transfer to a pose-cropped dance frame."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
PROJECT = ROOT / "workspace" / "dy_7671559890300685604"
MODEL_ROOT = PROJECT / "local_models"
INSIGHT_ROOT = MODEL_ROOT / "insightface"
SWAPPER_MODEL = INSIGHT_ROOT / "models" / "inswapper_128.onnx"
TRACKS = PROJECT / "motion" / "motion_tracks.json"
OUTPUT_DIR = PROJECT / "local_face_swap_proof"

ASSETS = {
    "female": ROOT / "assets" / "characters" / "change.png",
    "male": ROOT / "assets" / "characters" / "wukong.png",
}


def build_models(det_thresh: float):
    os.environ.setdefault("MPLCONFIGDIR", str(MODEL_ROOT / "cache" / "matplotlib"))
    os.environ.setdefault("NO_ALBUMENTATIONS_UPDATE", "1")
    from insightface import model_zoo
    from insightface.app import FaceAnalysis

    providers = ["CPUExecutionProvider"]
    analysis = FaceAnalysis(
        name="buffalo_l",
        root=str(INSIGHT_ROOT),
        allowed_modules=("detection", "recognition"),
        providers=providers,
    )
    analysis.prepare(ctx_id=-1, det_thresh=det_thresh, det_size=(640, 640))
    swapper = model_zoo.get_model(str(SWAPPER_MODEL), providers=providers)
    return analysis, swapper


def largest_face(faces):
    return max(faces, key=lambda face: float((face.bbox[2] - face.bbox[0]) * (face.bbox[3] - face.bbox[1])))


def expected_head(input_path: Path, frame_index: int, role: str) -> np.ndarray | None:
    metadata_path = input_path.with_suffix(".json")
    if not metadata_path.exists():
        return None
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    crop_box = metadata.get("crop_box")
    if not crop_box:
        return None
    tracks = json.loads(TRACKS.read_text(encoding="utf-8"))["frames"]
    nose = tracks[frame_index][role]["landmarks"][0]
    image = cv2.imread(str(input_path))
    left, top, right, bottom = crop_box
    return np.array([
        (nose[0] * 1254 - left) / (right - left) * image.shape[1],
        (nose[1] * 720 - top) / (bottom - top) * image.shape[0],
    ], dtype=np.float32)


def target_face(faces, expected: np.ndarray | None):
    if expected is None:
        return largest_face(faces)
    return min(
        faces,
        key=lambda face: float(np.linalg.norm(
            (np.asarray(face.bbox[:2]) + np.asarray(face.bbox[2:])) * 0.5 - expected
        )),
    )


def cosine_similarity(source_face, target) -> float:
    return float(np.dot(source_face.normed_embedding, target.normed_embedding))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--frame", type=int, required=True, choices=range(478))
    parser.add_argument("--role", choices=("female", "male"), required=True)
    parser.add_argument("--det-thresh", type=float, default=0.30)
    args = parser.parse_args()

    for path in (args.input, ASSETS[args.role], SWAPPER_MODEL):
        if not path.exists():
            raise FileNotFoundError(path)
    started = time.monotonic()
    analysis, swapper = build_models(args.det_thresh)
    source_image = cv2.imread(str(ASSETS[args.role]))
    target_image = cv2.imread(str(args.input))
    source_faces = analysis.get(source_image)
    target_faces = analysis.get(target_image)
    if not source_faces:
        raise RuntimeError(f"定妆图未检测到可用人脸: {ASSETS[args.role]}")
    if not target_faces:
        raise RuntimeError(f"角色裁片未检测到可用人脸: {args.input}")

    source = largest_face(source_faces)
    expected = expected_head(args.input, args.frame, args.role)
    target = target_face(target_faces, expected)
    before = cosine_similarity(source, target)
    result = swapper.get(target_image, target, source, paste_back=True)
    result_faces = analysis.get(result)
    after_face = target_face(result_faces, expected) if result_faces else None
    after = cosine_similarity(source, after_face) if after_face is not None else None

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / f"{args.input.stem}_swap_{args.role}.png"
    cv2.imwrite(str(output_path), result)
    payload = {
        "input": str(args.input),
        "output": str(output_path),
        "frame": args.frame,
        "role": args.role,
        "source_faces": len(source_faces),
        "target_faces": len(target_faces),
        "selected_target_bbox": [round(float(value), 2) for value in target.bbox],
        "expected_head": expected.tolist() if expected is not None else None,
        "identity_similarity_before": round(before, 4),
        "identity_similarity_after": round(after, 4) if after is not None else None,
        "seconds": round(time.monotonic() - started, 2),
        "model": str(SWAPPER_MODEL.relative_to(ROOT)),
    }
    output_path.with_suffix(".json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()

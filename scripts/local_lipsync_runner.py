#!/usr/bin/env python3
"""Apple Silicon compatibility runner for the community LatentSync MLX port."""

from __future__ import annotations

import runpy
import sys
import types
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "workspace" / ".local_ai" / "sources" / "latentsync-mlx"
CHECKPOINTS = SOURCE / "checkpoints"


def _install_decord_audio_shim() -> None:
    """The pipeline only needs Decord for reading the normalized WAV input."""
    import soundfile as sf

    class ArrayResult:
        def __init__(self, value: np.ndarray):
            self.value = value

        def asnumpy(self) -> np.ndarray:
            return self.value

    class AudioReader:
        def __init__(self, path: str, sample_rate: int = 16000, mono: bool = True):
            audio, source_rate = sf.read(path, dtype="float32", always_2d=True)
            if mono:
                audio = audio.mean(axis=1, keepdims=True)
            if source_rate != sample_rate:
                source_x = np.arange(len(audio), dtype=np.float64) / source_rate
                target_x = np.arange(round(len(audio) * sample_rate / source_rate), dtype=np.float64) / sample_rate
                audio = np.stack([
                    np.interp(target_x, source_x, audio[:, channel])
                    for channel in range(audio.shape[1])
                ], axis=1).astype(np.float32)
            self.audio = audio.T

        def __getitem__(self, item) -> ArrayResult:
            return ArrayResult(self.audio[item])

    class VideoReader:
        def __init__(self, *_args, **_kwargs):
            raise RuntimeError("LatentSync MLX uses OpenCV for video input on macOS")

    module = types.ModuleType("decord")
    module.AudioReader = AudioReader
    module.VideoReader = VideoReader
    sys.modules.setdefault("decord", module)


def _patch_face_detector() -> None:
    from insightface.app import FaceAnalysis
    from latentsync.utils import face_detector

    def init_for_macos(self, device: str = "mps") -> None:
        self.app = FaceAnalysis(
            name="buffalo_l",
            allowed_modules=["detection", "landmark_2d_106"],
            root=str(CHECKPOINTS / "auxiliary"),
            providers=["CPUExecutionProvider"],
        )
        self.app.prepare(
            ctx_id=-1,
            det_size=(face_detector.INSIGHTFACE_DETECT_SIZE, face_detector.INSIGHTFACE_DETECT_SIZE),
        )

    face_detector.FaceDetector.__init__ = init_for_macos


def _prepare_face_model() -> None:
    from insightface.app import FaceAnalysis

    app = FaceAnalysis(
        name="buffalo_l",
        allowed_modules=["detection", "landmark_2d_106"],
        root=str(CHECKPOINTS / "auxiliary"),
        providers=["CPUExecutionProvider"],
    )
    app.prepare(ctx_id=-1, det_size=(512, 512))


def main() -> None:
    if not SOURCE.is_dir():
        raise RuntimeError(f"LatentSync MLX source is missing: {SOURCE}")
    sys.path.insert(0, str(SOURCE))
    _install_decord_audio_shim()
    if sys.argv[1:] == ["--prepare-face-model"]:
        _prepare_face_model()
        return
    _patch_face_detector()
    runpy.run_path(str(SOURCE / "scripts" / "inference.py"), run_name="__main__")


if __name__ == "__main__":
    main()

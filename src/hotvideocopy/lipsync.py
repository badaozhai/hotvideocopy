"""Per-shot lip synchronization with an isolated LatentSync MLX process."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from .local_models import (
    CATALOG,
    REPO_ROOT,
    SOURCES_ROOT,
    run_isolated,
    runtime_python,
    serialized_model_task,
)
from .media import probe
from .workspace import slug, sub


SOURCE = SOURCES_ROOT / "latentsync-mlx"
CHECKPOINTS = SOURCE / "checkpoints"
RUNNER = REPO_ROOT / "scripts" / "local_lipsync_runner.py"


def _face_counts(video: Path, samples: int = 7) -> list[int]:
    try:
        import cv2
    except ImportError:
        return []
    if not hasattr(cv2, "CascadeClassifier") or not hasattr(cv2, "data"):
        return []
    capture = cv2.VideoCapture(str(video))
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    counts: list[int] = []
    if frame_count <= 0 or cascade.empty():
        capture.release()
        return counts
    for index in range(samples):
        frame_index = round((frame_count - 1) * index / max(1, samples - 1))
        capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = capture.read()
        if not ok:
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40))
        counts.append(len(faces))
    capture.release()
    return counts


@serialized_model_task("本地口型同步")
async def sync(
    video: str,
    audio: str,
    project_id: str,
    name: str = "",
    resolution: int = 256,
    inference_steps: int = 20,
    guidance_scale: float = 1.5,
    seed: int = 1247,
    audio_offset: float = 0.0,
    enforce_single_face: bool = True,
    timeout: int = 7200,
) -> dict:
    video_path = Path(video).expanduser().resolve()
    audio_path = Path(audio).expanduser().resolve()
    if not video_path.is_file():
        raise FileNotFoundError(f"找不到口型源视频：{video_path}")
    if not audio_path.is_file():
        raise FileNotFoundError(f"找不到口型音频：{audio_path}")
    if resolution not in {256, 512}:
        raise ValueError("LatentSync 分辨率只能是 256 或 512")
    if not 1 <= int(inference_steps) <= 100:
        raise ValueError("口型推理步数需要在 1 到 100 之间")
    if float(audio_offset) < 0:
        raise ValueError("口型音频起始偏移不能为负数")

    python = runtime_python(CATALOG["latentsync-mlx-1.5"].runtime)
    unet = CHECKPOINTS / "latentsync_unet_mlx.safetensors"
    vae = CHECKPOINTS / "vae_mlx.safetensors"
    if not python.is_file() or not RUNNER.is_file() or not unet.is_file() or not vae.is_file():
        raise RuntimeError(
            "LatentSync MLX 尚未完整安装。请执行："
            ".venv/bin/python scripts/local_media_models.py install lipsync --variant mlx"
        )

    source_info = await probe(video_path)
    source_duration = float(source_info.get("duration") or 0.0)
    source_fps = float(source_info.get("fps") or 30.0)
    if source_duration <= 0:
        raise RuntimeError("无法读取口型源视频时长")
    if float(audio_offset) >= source_duration:
        raise ValueError("口型音频起始偏移必须小于源视频时长")
    counts = _face_counts(video_path)
    if enforce_single_face and any(count > 1 for count in counts):
        raise RuntimeError(f"口型镜头检测到多张人脸 {counts}；请先裁成单人镜头")

    output = sub(project_id or "scratch", "gen", "lipsync", f"{slug(name, 'lipsync')}.mp4")
    with tempfile.TemporaryDirectory(prefix="hvc_lipsync_") as temp_dir:
        temp = Path(temp_dir)
        normalized_video = temp / "video_25fps.mp4"
        normalized_audio = temp / "audio.wav"
        raw_output = temp / "raw.mp4"
        subprocess.run([
            "ffmpeg", "-y", "-i", str(video_path), "-an", "-t", f"{source_duration:.6f}",
            "-vf", "fps=25", "-c:v", "libx264", "-preset", "fast", "-crf", "17",
            "-pix_fmt", "yuv420p", str(normalized_video),
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        audio_filter = "apad"
        if float(audio_offset) > 0:
            delay_ms = round(float(audio_offset) * 1000)
            audio_filter = f"adelay={delay_ms}:all=1,apad"
        subprocess.run([
            "ffmpeg", "-y", "-i", str(audio_path), "-af", audio_filter,
            "-t", f"{source_duration:.6f}", "-ar", "16000", "-ac", "1",
            "-c:a", "pcm_s16le", str(normalized_audio),
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        args = [
            str(python), str(RUNNER),
            "--video_path", str(normalized_video),
            "--audio_path", str(normalized_audio),
            "--video_out_path", str(raw_output),
            "--resolution", str(resolution),
            "--inference_steps", str(int(inference_steps)),
            "--guidance_scale", str(float(guidance_scale)),
            "--seed", str(int(seed)),
            "--unet_weights", str(unet),
            "--vae_weights", str(vae),
            "--temp_dir", str(temp / "pipeline"),
        ]
        run_isolated(args, timeout=timeout, cwd=SOURCE)
        if not raw_output.is_file() or raw_output.stat().st_size < 10_000:
            raise RuntimeError("LatentSync 没有生成有效视频")
        subprocess.run([
            "ffmpeg", "-y", "-i", str(raw_output), "-i", str(normalized_audio),
            "-map", "0:v:0", "-map", "1:a:0", "-t", f"{source_duration:.6f}",
            "-r", f"{source_fps:.6f}", "-c:v", "libx264", "-preset", "medium",
            "-crf", "17", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
            "-movflags", "+faststart", str(output),
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    result_info = await probe(output)
    result_duration = float(result_info.get("duration") or 0.0)
    if abs(result_duration - source_duration) > max(0.05, 1.0 / source_fps):
        raise RuntimeError(
            f"口型输出时长漂移：源 {source_duration:.3f}s，输出 {result_duration:.3f}s"
        )
    return {
        "path": str(output),
        "bytes": output.stat().st_size,
        "duration": result_duration,
        "fps": result_info.get("fps") or source_fps,
        "engine": "latentsync-mlx-1.5",
        "experimental": True,
        "face_counts": counts,
        "single_face_gate": not any(count > 1 for count in counts),
        "audio_offset": float(audio_offset),
        "memory_released": True,
    }

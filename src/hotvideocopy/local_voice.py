"""Apple Silicon local voice synthesis through an isolated MLX-Audio runtime."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from .local_models import CATALOG, runtime_python, run_isolated, write_job_manifest
from .media import probe
from .workspace import slug, sub


RUNNER = Path(__file__).resolve().parents[2] / "scripts" / "local_voice_runner.py"
PRESET_VOICES = {
    "记者": "Dylan",
    "养殖大爷": "Uncle_Fu",
    "养殖大妈": "Serena",
    "青年技术员": "Dylan",
    "青年记录员": "Vivian",
}

SUPPORTED_VOICES = {
    "Aiden", "Dylan", "Eric", "Ono_Anna", "Ryan", "Serena", "Sohee",
    "Uncle_Fu", "Vivian",
}

VOICE_ALIASES = {
    "alloy": "Dylan",
    "echo": "Dylan",
    "onyx": "Uncle_Fu",
    "nova": "Vivian",
    "shimmer": "Serena",
    "zh-cn-yunxineural": "Dylan",
    "zh-cn-yunjianneural": "Dylan",
    "zh-cn-yunyangneural": "Dylan",
    "zh-cn-xiaoxiaoneural": "Vivian",
    "zh-cn-xiaoyineural": "Serena",
}


def normalize_voice(voice: str) -> str:
    """Map API/Edge/role labels to a Qwen CustomVoice speaker."""
    candidate = str(voice or "").strip()
    if candidate in PRESET_VOICES:
        return PRESET_VOICES[candidate]
    if candidate in SUPPORTED_VOICES:
        return candidate
    return VOICE_ALIASES.get(candidate.lower(), "Dylan")


async def generate(
    text: str,
    project_id: str,
    name: str,
    voice: str = "",
    instruction: str = "",
    language: str = "Chinese",
    reference_audio: str = "",
    reference_text: str = "",
    consent: bool = False,
    model: str = "",
    speed: float = 1.0,
    timeout: int = 1800,
) -> dict:
    body_text = str(text or "").strip()
    if not body_text:
        raise ValueError("缺少要合成的文本")
    cloning = bool(reference_audio)
    if cloning and not consent:
        raise ValueError("音色克隆必须确认已获得参考音色的使用授权")
    if cloning and not str(reference_text or "").strip():
        raise ValueError("音色克隆需要填写与参考音频逐字对应的文字")
    if not 0.5 <= float(speed or 1.0) <= 2.0:
        raise ValueError("本地语音语速需要在 0.5 到 2.0 之间")
    model_key = model or ("qwen3-tts-clone-8bit" if cloning else "qwen3-tts-custom-8bit")
    spec = CATALOG.get(model_key)
    if not spec or spec.component != "voice":
        raise ValueError(f"未知本地语音模型：{model_key}")
    python = runtime_python(spec.runtime)
    if not python.is_file():
        raise RuntimeError(
            "本地 MLX 语音运行时尚未安装。请先执行："
            ".venv/bin/python scripts/local_media_models.py install voice"
        )

    reference = Path(reference_audio).expanduser().resolve() if reference_audio else None
    if reference and not reference.is_file():
        raise FileNotFoundError(f"找不到音色参考：{reference}")
    output = sub(project_id or "scratch", "gen", "local_voice", f"{slug(name, 'line')}.wav")
    request = {
        "text": body_text,
        "output": str(output),
        "model_id": spec.model_id,
        "mode": "clone" if cloning else "custom",
        "voice": normalize_voice(voice),
        "instruction": instruction,
        "language": language or "Chinese",
        "reference_audio": str(reference) if reference else "",
        "reference_text": reference_text,
    }
    stamp = f"voice_{int(time.time() * 1000)}"
    request_path = write_job_manifest(stamp, request)
    result = run_isolated([str(python), str(RUNNER), str(request_path)], timeout=timeout)
    try:
        response = json.loads(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError) as exc:
        raise RuntimeError(f"本地语音输出无法解析：{result.stdout[-600:]}") from exc
    if not output.is_file() or output.stat().st_size < 1000:
        raise RuntimeError("本地语音模型没有生成有效音频")
    if abs(float(speed or 1.0) - 1.0) > 0.001:
        adjusted = output.with_name(output.stem + ".speed.wav")
        try:
            subprocess.run([
                "ffmpeg", "-y", "-i", str(output), "-filter:a", f"atempo={float(speed):.4f}",
                "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le", str(adjusted),
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            adjusted.replace(output)
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr.decode("utf-8", "replace")[-600:] if exc.stderr else ""
            raise RuntimeError(f"本地语音语速处理失败：{detail}") from None
    info = await probe(output)
    return {
        "path": str(output),
        "bytes": output.stat().st_size,
        "duration": info.get("duration") or response.get("duration") or 0.0,
        "engine": "local-mlx",
        "model": model_key,
        "model_id": spec.model_id,
        "voice": request["voice"],
        "language": request["language"],
        "instruction": instruction,
        "speed": float(speed or 1.0),
        "cloned": cloning,
        "memory_released": True,
    }

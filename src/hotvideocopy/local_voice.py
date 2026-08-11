"""Apple Silicon local voice synthesis through an isolated MLX-Audio runtime."""

from __future__ import annotations

import json
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
    timeout: int = 1800,
) -> dict:
    body_text = str(text or "").strip()
    if not body_text:
        raise ValueError("缺少要合成的文本")
    cloning = bool(reference_audio)
    if cloning and not consent:
        raise ValueError("音色克隆必须确认已获得参考音色的使用授权")
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
        "voice": voice or "Dylan",
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
        "cloned": cloning,
        "memory_released": True,
    }

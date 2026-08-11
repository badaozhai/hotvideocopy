"""Local media model registry and isolated runtime helpers.

Heavy models never load in the hotvideocopy process. Each inference runs in a
short-lived child process so Apple unified memory is returned to the OS when
the command exits. Model weights and runtimes live under workspace/.local_ai,
which is already outside version control and can be purged independently.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from .config import CONFIG


LOCAL_AI_ROOT = CONFIG.workspace / ".local_ai"
RUNTIMES_ROOT = LOCAL_AI_ROOT / "runtimes"
SOURCES_ROOT = LOCAL_AI_ROOT / "sources"
MODELS_ROOT = LOCAL_AI_ROOT / "models"
CACHE_ROOT = LOCAL_AI_ROOT / "cache"
JOBS_ROOT = LOCAL_AI_ROOT / "jobs"


@dataclass(frozen=True)
class ModelSpec:
    id: str
    component: str
    title: str
    runtime: str
    model_id: str
    params: str
    memory: str
    license: str
    hardware: str
    capabilities: tuple[str, ...]
    default: bool = False
    experimental: bool = False
    notes: str = ""


CATALOG: dict[str, ModelSpec] = {
    "qwen3-tts-custom-8bit": ModelSpec(
        id="qwen3-tts-custom-8bit",
        component="voice",
        title="Qwen3-TTS CustomVoice 1.7B 8-bit (MLX)",
        runtime="mlx-audio",
        model_id="mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit",
        params="1.7B / 8-bit",
        memory="约 3-5 GB 统一内存",
        license="Apache-2.0 model / MIT runtime",
        hardware="Apple Silicon",
        capabilities=("中文", "北京话", "四川话", "情感指令", "语速", "角色预设"),
        default=True,
        notes="当前机器的默认高拟真角色配音模型。",
    ),
    "qwen3-tts-clone-8bit": ModelSpec(
        id="qwen3-tts-clone-8bit",
        component="voice",
        title="Qwen3-TTS Base 1.7B 8-bit (MLX)",
        runtime="mlx-audio",
        model_id="mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit",
        params="1.7B / 8-bit",
        memory="约 3-5 GB 统一内存",
        license="Apache-2.0 model / MIT runtime",
        hardware="Apple Silicon",
        capabilities=("3秒音色克隆", "中文", "跨语言", "参考语气"),
        notes="只有获得音色授权并提供参考音频时使用。",
    ),
    "cosyvoice3-0.5b": ModelSpec(
        id="cosyvoice3-0.5b",
        component="voice",
        title="Fun-CosyVoice 3 0.5B",
        runtime="cosyvoice3",
        model_id="FunAudioLLM/Fun-CosyVoice3-0.5B-2512",
        params="0.5B",
        memory="CPU 推理约 6-10 GB 内存",
        license="Apache-2.0 code; model card terms apply",
        hardware="Linux CUDA preferred; macOS CPU fallback",
        capabilities=("18+中国方言", "情感指令", "零样本克隆", "跨语言", "流式"),
        notes="方言覆盖最全，但本机 CPU 推理明显慢于 MLX。",
    ),
    "indextts-2.5": ModelSpec(
        id="indextts-2.5",
        component="voice",
        title="IndexTTS 2.5",
        runtime="indextts",
        model_id="IndexTeam/IndexTTS-2.5",
        params="0.8B",
        memory="官方以 CUDA 为主",
        license="Model repository terms apply",
        hardware="CUDA preferred",
        capabilities=("音色克隆", "8维情感", "情感参考", "语速", "拼音控制"),
        notes="精细情绪备选，不作为 16GB M1 Pro 默认。",
    ),
    "ace-step-1.5-turbo": ModelSpec(
        id="ace-step-1.5-turbo",
        component="music",
        title="ACE-Step 1.5 Turbo (MLX)",
        runtime="ace-step",
        model_id="ACE-Step/Ace-Step1.5",
        params="2B DiT + optional 0.6B LM",
        memory="官方低显存档小于 6 GB",
        license="MIT",
        hardware="Apple Silicon MLX / CUDA / CPU",
        capabilities=("歌词", "段落结构", "BPM", "调式", "拍号", "1000+乐器风格", "重绘", "分轨"),
        default=True,
    ),
    "latentsync-mlx-1.5": ModelSpec(
        id="latentsync-mlx-1.5",
        component="lipsync",
        title="LatentSync 1.5 MLX",
        runtime="latentsync-mlx",
        model_id="ByteDance/LatentSync-1.5",
        params="SD1.5 UNet / 256px face",
        memory="约 8 GB 统一内存起",
        license="Apache-2.0",
        hardware="Apple Silicon community port",
        capabilities=("中文音频", "视频后期口型", "身份保持", "单人脸"),
        default=True,
        experimental=True,
        notes="社区 MLX 移植较新，逐镜 QC 后才能进入成片。",
    ),
    "musetalk-1.5": ModelSpec(
        id="musetalk-1.5",
        component="lipsync",
        title="MuseTalk 1.5",
        runtime="musetalk",
        model_id="TMElyralab/MuseTalk",
        params="single-step latent inpainting",
        memory="4 GB VRAM 起",
        license="MIT code; dependency model terms apply",
        hardware="NVIDIA CUDA preferred",
        capabilities=("中文音频", "实时口型", "256px人脸", "单人脸"),
        notes="官方高配路径；本机仅保留安装与调度接口。",
    ),
}


def ensure_layout() -> None:
    for path in (RUNTIMES_ROOT, SOURCES_ROOT, MODELS_ROOT, CACHE_ROOT, JOBS_ROOT):
        path.mkdir(parents=True, exist_ok=True)


def runtime_python(runtime: str) -> Path:
    return RUNTIMES_ROOT / runtime / "bin" / "python"


def _dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file() and not item.is_symlink():
                total += item.stat().st_size
        except OSError:
            pass
    return total


def _model_cache_path(model_id: str) -> Path:
    return CACHE_ROOT / "huggingface" / "hub" / ("models--" + model_id.replace("/", "--"))


def model_installed(spec: ModelSpec) -> bool:
    if spec.runtime == "ace-step":
        return (SOURCES_ROOT / "ACE-Step-1.5" / "pyproject.toml").is_file()
    if spec.runtime == "latentsync-mlx":
        return (SOURCES_ROOT / "latentsync-mlx" / "pyproject.toml").is_file()
    if spec.runtime == "musetalk":
        return (SOURCES_ROOT / "MuseTalk" / "README.md").is_file()
    if spec.runtime == "cosyvoice3":
        return (SOURCES_ROOT / "CosyVoice" / "README.md").is_file()
    return _model_cache_path(spec.model_id).is_dir()


def local_environment() -> dict[str, str]:
    ensure_layout()
    env = os.environ.copy()
    env.update({
        "HF_HOME": str(CACHE_ROOT / "huggingface"),
        "HF_HUB_CACHE": str(CACHE_ROOT / "huggingface" / "hub"),
        "MODELSCOPE_CACHE": str(CACHE_ROOT / "modelscope"),
        "XDG_CACHE_HOME": str(CACHE_ROOT / "xdg"),
        "PYTORCH_ENABLE_MPS_FALLBACK": "1",
        "TOKENIZERS_PARALLELISM": "false",
    })
    if CONFIG.hf_token:
        env["HF_TOKEN"] = CONFIG.hf_token
    if CONFIG.proxy:
        env.setdefault("HTTPS_PROXY", CONFIG.proxy)
        env.setdefault("HTTP_PROXY", CONFIG.proxy)
    return env


def run_isolated(args: list[str], timeout: int = 3600, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Run one model task in a child process; no shell and no resident model."""
    if not args or not Path(args[0]).exists():
        raise RuntimeError(f"本地模型运行时不存在：{args[0] if args else '(empty)'}")
    try:
        return subprocess.run(
            args,
            cwd=str(cwd) if cwd else None,
            env=local_environment(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=True,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"本地模型运行超时（{timeout} 秒）") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "本地模型运行失败")[-1200:]
        raise RuntimeError(detail.strip()) from None


def hardware_info() -> dict:
    total_bytes = shutil.disk_usage(CONFIG.workspace).total
    free_bytes = shutil.disk_usage(CONFIG.workspace).free
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "apple_silicon": platform.system() == "Darwin" and platform.machine() == "arm64",
        "disk_total": total_bytes,
        "disk_free": free_bytes,
    }


def status() -> dict:
    ensure_layout()
    runtime_names = sorted({spec.runtime for spec in CATALOG.values()})
    return {
        "root": str(LOCAL_AI_ROOT),
        "hardware": hardware_info(),
        "disk_bytes": _dir_size(LOCAL_AI_ROOT),
        "runtimes": {
            name: {
                "installed": runtime_python(name).is_file(),
                "python": str(runtime_python(name)),
                "bytes": _dir_size(RUNTIMES_ROOT / name),
            }
            for name in runtime_names
        },
        "models": [
            {
                **asdict(spec),
                "capabilities": list(spec.capabilities),
                "installed": model_installed(spec),
                "cache_path": str(_model_cache_path(spec.model_id)),
                "cache_bytes": _dir_size(_model_cache_path(spec.model_id)),
            }
            for spec in CATALOG.values()
        ],
        "lifecycle": "isolated-process",
        "memory_release": "child process exits after every task",
    }


def write_job_manifest(name: str, payload: dict) -> Path:
    ensure_layout()
    target = JOBS_ROOT / f"{name}.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target

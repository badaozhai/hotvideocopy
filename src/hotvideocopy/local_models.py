"""Local media model registry and isolated runtime helpers.

Heavy models never load in the hotvideocopy process. Each inference runs in a
short-lived child process so Apple unified memory is returned to the OS when
the command exits. Model weights and runtimes live under workspace/.local_ai,
which is outside version control and persists until an explicit user-requested
purge.
"""

from __future__ import annotations

import asyncio
import fcntl
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import asynccontextmanager, contextmanager
from dataclasses import asdict, dataclass
from functools import wraps
from pathlib import Path
from typing import Awaitable, Callable, ParamSpec, TypeVar

import httpx

from .config import CONFIG


LOCAL_AI_ROOT = CONFIG.workspace / ".local_ai"
RUNTIMES_ROOT = LOCAL_AI_ROOT / "runtimes"
SOURCES_ROOT = LOCAL_AI_ROOT / "sources"
MODELS_ROOT = LOCAL_AI_ROOT / "models"
CACHE_ROOT = LOCAL_AI_ROOT / "cache"
JOBS_ROOT = LOCAL_AI_ROOT / "jobs"
INSTALL_MANIFEST = LOCAL_AI_ROOT / "install_manifest.json"
MODEL_TASK_LOCK = LOCAL_AI_ROOT / ".model-task.lock"
REPO_ROOT = Path(__file__).resolve().parents[2]
FETCH_RUNNER = REPO_ROOT / "scripts" / "local_model_fetch.py"
LIPSYNC_RUNNER = REPO_ROOT / "scripts" / "local_lipsync_runner.py"

GIB = 1024 ** 3
MIN_FREE_RESERVE = GIB
DOWNLOAD_PROBE_BYTES = 2 * 1024 * 1024
DIRECT_MIN_BYTES_PER_SECOND = 1024 * 1024
LOCAL_MODEL_PROXY = "http://127.0.0.1:8080"
MODEL_TASK_POLL_SECONDS = 0.25
MODEL_TASK_WAIT_TIMEOUT = 12 * 60 * 60
DOWNLOAD_PROBE_URL = (
    "https://huggingface.co/mlx-community/"
    "Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit/resolve/main/model.safetensors"
)

P = ParamSpec("P")
R = TypeVar("R")


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
        capabilities=("歌词", "段落结构", "BPM", "调式", "拍号", "提示词乐器与风格", "翻唱", "重绘"),
        default=True,
        notes="当前安装 Turbo 版；分轨、Lego 和补全只属于未安装的 Base 版。",
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


COMPONENT_MODELS: dict[str, dict[str, tuple[str, ...]]] = {
    "voice": {
        "custom": ("qwen3-tts-custom-8bit",),
        "clone": ("qwen3-tts-clone-8bit",),
        "all": ("qwen3-tts-custom-8bit", "qwen3-tts-clone-8bit"),
    },
    "music": {"default": ("ace-step-1.5-turbo",)},
    "lipsync": {
        "mlx": ("latentsync-mlx-1.5",),
        "cuda": ("musetalk-1.5",),
    },
}

# Includes runtime, source and model weights. Estimates are deliberately
# conservative because upstream repositories can add files without notice.
INSTALL_ESTIMATES = {
    ("voice", "custom"): int(3.6 * GIB),
    ("voice", "clone"): int(3.6 * GIB),
    ("voice", "all"): int(6.0 * GIB),
    ("music", "default"): int(12 * GIB),
    ("lipsync", "mlx"): int(10 * GIB),
    ("lipsync", "cuda"): int(12 * GIB),
}

SOURCE_SPECS = {
    "music": (
        "ACE-Step-1.5",
        "https://github.com/ACE-Step/ACE-Step-1.5.git",
        "ace-step",
    ),
    "lipsync-mlx": (
        "latentsync-mlx",
        "https://github.com/sb1992/latentsync-mlx.git",
        "latentsync-mlx",
    ),
    "latentsync-upstream": (
        "LatentSync",
        "https://github.com/bytedance/LatentSync.git",
        "latentsync-mlx",
    ),
    "lipsync-cuda": (
        "MuseTalk",
        "https://github.com/TMElyralab/MuseTalk.git",
        "musetalk",
    ),
}


def ensure_layout() -> None:
    for path in (RUNTIMES_ROOT, SOURCES_ROOT, MODELS_ROOT, CACHE_ROOT, JOBS_ROOT):
        path.mkdir(parents=True, exist_ok=True)


def runtime_python(runtime: str) -> Path:
    return RUNTIMES_ROOT / runtime / "bin" / "python"


def _read_manifest() -> dict:
    try:
        data = json.loads(INSTALL_MANIFEST.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _write_manifest(data: dict) -> None:
    ensure_layout()
    temp = INSTALL_MANIFEST.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(INSTALL_MANIFEST)


def _record_install(component: str, variant: str, models: tuple[str, ...]) -> None:
    data = _read_manifest()
    entries = data.setdefault("installs", {})
    entries[f"{component}:{variant}"] = {
        "component": component,
        "variant": variant,
        "models": list(models),
        "installed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    data["schema_version"] = "1.0"
    data["retention_policy"] = "persistent_until_explicit_purge"
    data["automatic_cleanup"] = False
    _write_manifest(data)


def _drop_install_records(component: str, variants: set[str] | None = None) -> None:
    data = _read_manifest()
    entries = data.get("installs")
    if not isinstance(entries, dict):
        return
    for key, value in list(entries.items()):
        if not isinstance(value, dict) or value.get("component") != component:
            continue
        if variants is None or str(value.get("variant")) in variants:
            entries.pop(key, None)
    _write_manifest(data)


def _lock_holder() -> dict:
    try:
        value = json.loads(MODEL_TASK_LOCK.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _try_model_task_lock(task: str) -> int | None:
    ensure_layout()
    fd = os.open(MODEL_TASK_LOCK, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return None
    payload = {
        "pid": os.getpid(),
        "task": str(task or "local-model-task"),
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    os.ftruncate(fd, 0)
    os.lseek(fd, 0, os.SEEK_SET)
    os.write(fd, json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    return fd


def _release_model_task_lock(fd: int) -> None:
    try:
        os.ftruncate(fd, 0)
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _lock_timeout_message(task: str) -> str:
    holder = _lock_holder()
    active = str(holder.get("task") or "另一个本地模型任务")
    pid = int(holder.get("pid") or 0)
    suffix = f"（PID {pid}）" if pid else ""
    return f"{task} 等待本地模型队列超时；当前任务：{active}{suffix}"


@contextmanager
def model_task_guard(task: str, wait_timeout: float = MODEL_TASK_WAIT_TIMEOUT):
    """Serialize every heavyweight local-model operation across processes."""
    deadline = time.monotonic() + max(0.0, float(wait_timeout))
    fd: int | None = None
    while fd is None:
        fd = _try_model_task_lock(task)
        if fd is not None:
            break
        if time.monotonic() >= deadline:
            raise RuntimeError(_lock_timeout_message(task))
        time.sleep(MODEL_TASK_POLL_SECONDS)
    try:
        yield
    finally:
        _release_model_task_lock(fd)


@asynccontextmanager
async def async_model_task_guard(task: str, wait_timeout: float = MODEL_TASK_WAIT_TIMEOUT):
    """Async queue for voice, music and lip-sync entry points."""
    deadline = time.monotonic() + max(0.0, float(wait_timeout))
    fd: int | None = None
    while fd is None:
        fd = _try_model_task_lock(task)
        if fd is not None:
            break
        if time.monotonic() >= deadline:
            raise RuntimeError(_lock_timeout_message(task))
        await asyncio.sleep(MODEL_TASK_POLL_SECONDS)
    try:
        yield
    finally:
        _release_model_task_lock(fd)


def serialized_model_task(task: str) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Queue an async model entry point behind the shared process lock."""
    def decorate(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @wraps(func)
        async def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            async with async_model_task_guard(task):
                return await func(*args, **kwargs)

        return wrapped

    return decorate


@contextmanager
def install_guard():
    """Keep installs and purges mutually exclusive with inference jobs."""
    with model_task_guard("模型安装或显式清理"):
        yield


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


def _model_storage_path(spec: ModelSpec) -> Path:
    if spec.runtime == "ace-step":
        return SOURCES_ROOT / "ACE-Step-1.5" / "checkpoints"
    if spec.runtime == "latentsync-mlx":
        return SOURCES_ROOT / "latentsync-mlx" / "checkpoints"
    if spec.runtime == "musetalk":
        return SOURCES_ROOT / "MuseTalk" / "models"
    return _model_cache_path(spec.model_id)


def _valid_weight(path: Path, minimum_bytes: int = 1024 * 1024) -> bool:
    try:
        return path.is_file() and path.stat().st_size >= minimum_bytes
    except OSError:
        return False


def model_installed(spec: ModelSpec) -> bool:
    if spec.runtime == "ace-step":
        checkpoints = _model_storage_path(spec)
        return (
            runtime_python(spec.runtime).is_file()
            and _valid_weight(checkpoints / "acestep-v15-turbo" / "model.safetensors", GIB)
            and _valid_weight(checkpoints / "vae" / "diffusion_pytorch_model.safetensors", 100 * 1024 * 1024)
            and _valid_weight(checkpoints / "Qwen3-Embedding-0.6B" / "model.safetensors", GIB)
        )
    if spec.runtime == "latentsync-mlx":
        checkpoints = _model_storage_path(spec)
        return (
            runtime_python(spec.runtime).is_file()
            and _valid_weight(checkpoints / "latentsync_unet_mlx.safetensors")
            and _valid_weight(checkpoints / "vae_mlx.safetensors")
            and _valid_weight(checkpoints / "whisper" / "tiny.pt", 50 * 1024 * 1024)
            and _valid_weight(
                checkpoints / "auxiliary" / "models" / "buffalo_l" / "det_10g.onnx",
                10 * 1024 * 1024,
            )
            and _valid_weight(
                checkpoints / "auxiliary" / "models" / "buffalo_l" / "2d106det.onnx",
                1024 * 1024,
            )
        )
    if spec.runtime == "musetalk":
        return (SOURCES_ROOT / "MuseTalk" / "README.md").is_file()
    if spec.runtime == "cosyvoice3":
        return (SOURCES_ROOT / "CosyVoice" / "README.md").is_file()
    snapshots = _model_cache_path(spec.model_id) / "snapshots"
    if not snapshots.is_dir():
        return False
    for snapshot in snapshots.iterdir():
        if not snapshot.is_dir() or not (snapshot / "config.json").is_file():
            continue
        weights = list(snapshot.glob("*.safetensors")) + list(snapshot.glob("*.bin"))
        if any(path.is_file() and path.stat().st_size > 1024 * 1024 for path in weights):
            return True
    return False


def component_variant(component: str, variant: str = "") -> tuple[str, tuple[str, ...]]:
    component = str(component or "").strip().lower()
    variants = COMPONENT_MODELS.get(component)
    if not variants:
        raise ValueError(f"未知本地模型组件：{component or '(空)'}")
    selected = str(variant or "").strip().lower()
    if not selected:
        selected = "custom" if component == "voice" else ("mlx" if component == "lipsync" else "default")
    if selected not in variants:
        choices = "、".join(variants)
        raise ValueError(f"{component} 不支持变体 {selected}；可选：{choices}")
    return selected, variants[selected]


def estimate_install(component: str, variant: str = "") -> dict:
    selected, model_keys = component_variant(component, variant)
    estimate = INSTALL_ESTIMATES[(component, selected)]
    if component == "music":
        already = _dir_size(SOURCES_ROOT / "ACE-Step-1.5") + _dir_size(RUNTIMES_ROOT / "ace-step")
    elif component == "lipsync" and selected == "mlx":
        already = (
            _dir_size(SOURCES_ROOT / "latentsync-mlx")
            + _dir_size(SOURCES_ROOT / "LatentSync")
            + _dir_size(RUNTIMES_ROOT / "latentsync-mlx")
        )
    else:
        already = sum(_dir_size(_model_storage_path(CATALOG[key])) for key in model_keys)
    needed = max(0, estimate - already)
    free = shutil.disk_usage(CONFIG.workspace).free
    return {
        "component": component,
        "variant": selected,
        "models": list(model_keys),
        "estimated_total_bytes": estimate,
        "already_present_bytes": already,
        "estimated_additional_bytes": needed,
        "free_bytes": free,
        "reserve_bytes": MIN_FREE_RESERVE,
        "enough_space": free - needed >= MIN_FREE_RESERVE,
    }


def _run_command(
    args: list[str],
    cwd: Path | None = None,
    timeout: int = 7200,
    download_route: str = "configured",
) -> None:
    if shutil.disk_usage(CONFIG.workspace).free < MIN_FREE_RESERVE:
        raise RuntimeError("本地模型任务未启动：可用磁盘空间低于 1 GiB 安全线")
    env = local_environment(download_route)
    process: subprocess.Popen | None = None
    try:
        process = subprocess.Popen(
            args,
            cwd=str(cwd) if cwd else None,
            env=env,
        )
        deadline = time.monotonic() + timeout
        while True:
            try:
                return_code = process.wait(timeout=min(1.0, max(0.1, deadline - time.monotonic())))
                break
            except subprocess.TimeoutExpired:
                if shutil.disk_usage(CONFIG.workspace).free < MIN_FREE_RESERVE:
                    process.terminate()
                    try:
                        process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                    raise RuntimeError("本地模型任务已停止：可用磁盘空间低于 1 GiB 安全线")
                if time.monotonic() >= deadline:
                    process.terminate()
                    try:
                        process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                    raise RuntimeError(f"安装步骤超时（{timeout} 秒）：{' '.join(args[:3])}")
        if return_code != 0:
            raise RuntimeError(f"安装步骤失败（退出码 {return_code}）：{' '.join(args[:4])}")
    except FileNotFoundError as exc:
        raise RuntimeError(f"缺少命令：{args[0]}") from exc


def _ensure_runtime(
    runtime: str,
    packages: list[str],
    download_route: str = "configured",
) -> Path:
    python = runtime_python(runtime)
    if not python.is_file():
        target = RUNTIMES_ROOT / runtime
        target.parent.mkdir(parents=True, exist_ok=True)
        _run_command(
            [sys.executable, "-m", "venv", str(target)],
            timeout=900,
            download_route=download_route,
        )
    if packages:
        _run_command([
            str(python), "-m", "pip", "install", "--disable-pip-version-check",
            "--no-cache-dir", *packages,
        ], download_route=download_route)
    return python


def _clone_source(source_key: str, download_route: str = "configured") -> Path:
    dirname, url, _ = SOURCE_SPECS[source_key]
    target = SOURCES_ROOT / dirname
    if target.is_dir():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    _run_command(
        ["git", "clone", "--depth", "1", url, str(target)],
        download_route=download_route,
    )
    return target


def _probe_download_route(url: str, route: str, proxy: str | None) -> dict:
    started = time.monotonic()
    downloaded = 0
    try:
        with httpx.Client(
            proxy=proxy,
            trust_env=False,
            follow_redirects=True,
            timeout=httpx.Timeout(20.0, connect=5.0),
        ) as client:
            with client.stream(
                "GET",
                url,
                headers={"Range": f"bytes=0-{DOWNLOAD_PROBE_BYTES - 1}"},
            ) as response:
                response.raise_for_status()
                for chunk in response.iter_bytes(256 * 1024):
                    downloaded += len(chunk)
                    if downloaded >= DOWNLOAD_PROBE_BYTES:
                        break
        elapsed = max(0.001, time.monotonic() - started)
        return {
            "route": route,
            "ok": downloaded > 0,
            "bytes": downloaded,
            "seconds": round(elapsed, 3),
            "bytes_per_second": int(downloaded / elapsed),
        }
    except (httpx.HTTPError, OSError) as exc:
        return {
            "route": route,
            "ok": False,
            "bytes": downloaded,
            "seconds": round(time.monotonic() - started, 3),
            "bytes_per_second": 0,
            "error": type(exc).__name__,
        }


def _proxy_candidates() -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    seen: set[str] = set()
    if CONFIG.proxy:
        normalized = CONFIG.proxy.rstrip("/")
        candidates.append(("configured", CONFIG.proxy))
        seen.add(normalized)
    if LOCAL_MODEL_PROXY.rstrip("/") not in seen:
        candidates.append(("local-8080", LOCAL_MODEL_PROXY))
    return candidates


def select_download_route(spec: ModelSpec) -> dict:
    """Try direct first; only benchmark proxies when direct is too slow."""
    direct = _probe_download_route(DOWNLOAD_PROBE_URL, "direct", None)
    if direct["ok"] and direct["bytes_per_second"] >= DIRECT_MIN_BYTES_PER_SECOND:
        return {"selected": "direct", "model": spec.id, "probes": [direct]}

    probes = [direct]
    probes.extend(
        _probe_download_route(DOWNLOAD_PROBE_URL, name, proxy)
        for name, proxy in _proxy_candidates()
    )
    viable = [probe for probe in probes if probe["ok"]]
    if viable:
        selected = max(viable, key=lambda item: item["bytes_per_second"])["route"]
    else:
        # Some mirrors block ranged probes but still support the Hub client.
        selected = "configured" if CONFIG.proxy else "direct"
    return {"selected": selected, "model": spec.id, "probes": probes}


def _run_download_command(args: list[str], route: dict) -> dict:
    """Run a resumable download and fall back to the next measured route."""
    selected = str(route["selected"])
    attempts: list[dict] = []

    while True:
        try:
            _run_command(args, download_route=selected)
            result = dict(route)
            result["actual"] = selected
            result["attempts"] = attempts + [{"route": selected, "ok": True}]
            return result
        except RuntimeError as exc:
            attempts.append({"route": selected, "ok": False, "error": str(exc)})

        measured = {
            str(probe.get("route")): probe
            for probe in route.get("probes", [])
            if isinstance(probe, dict)
        }
        for name, proxy in _proxy_candidates():
            if name not in measured:
                probe = _probe_download_route(DOWNLOAD_PROBE_URL, name, proxy)
                route.setdefault("probes", []).append(probe)
                measured[name] = probe

        tried = {str(item["route"]) for item in attempts}
        viable = [
            probe for probe in measured.values()
            if probe.get("ok") and str(probe.get("route")) not in tried
        ]
        if not viable:
            routes = "、".join(str(item["route"]) for item in attempts)
            raise RuntimeError(f"模型下载失败，已尝试线路：{routes}") from None
        selected = str(max(viable, key=lambda item: item["bytes_per_second"])["route"])


def _download_model(python: Path, spec: ModelSpec) -> dict:
    if not FETCH_RUNNER.is_file():
        raise RuntimeError(f"缺少模型下载器：{FETCH_RUNNER}")
    if model_installed(spec):
        return {"selected": "cache", "actual": "cache", "probes": []}
    route = select_download_route(spec)
    args = [
        str(python), str(FETCH_RUNNER), "--repo", spec.model_id,
        "--cache-dir", str(CACHE_ROOT / "huggingface" / "hub"),
    ]
    # The Hub client keeps partial blobs in the same cache, so changing route
    # after a failure resumes instead of restarting a multi-gigabyte file.
    return _run_download_command(args, route)


def _download_local_snapshot(
    python: Path,
    spec: ModelSpec,
    local_dir: Path,
    allow_patterns: tuple[str, ...],
    route: dict,
) -> dict:
    args = [
        str(python), str(FETCH_RUNNER), "--repo", spec.model_id,
        "--local-dir", str(local_dir),
    ]
    for pattern in allow_patterns:
        args.extend(["--allow-pattern", pattern])
    result = _run_download_command(args, route)
    result["allow_patterns"] = list(allow_patterns)
    return result


def _install_voice(variant: str, model_keys: tuple[str, ...]) -> list[dict]:
    bootstrap = select_download_route(CATALOG[model_keys[0]])
    python = _ensure_runtime("mlx-audio", [
        "mlx-audio", "huggingface-hub>=0.28", "numpy", "soundfile",
    ], download_route=bootstrap["selected"])
    return [_download_model(python, CATALOG[key]) for key in model_keys]


def _install_music() -> list[dict]:
    route = select_download_route(CATALOG["ace-step-1.5-turbo"])
    selected = route["selected"]
    source = _clone_source("music", selected)
    python = _ensure_runtime("ace-step", [], selected)
    import_check = subprocess.run(
        [
            str(python), "-c",
            "from importlib.metadata import version; "
            "version('ace-step'); import huggingface_hub, uvicorn, torch, mlx",
        ],
        cwd=str(source),
        env=local_environment(selected),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if import_check.returncode != 0:
        _run_command([
            str(python), "-m", "pip", "install", "--disable-pip-version-check",
            "--no-cache-dir", "-e", str(source),
        ], download_route=selected)
    model_route = _download_local_snapshot(
        python,
        CATALOG["ace-step-1.5-turbo"],
        source / "checkpoints",
        (
            "acestep-v15-turbo/*",
            "vae/*",
            "Qwen3-Embedding-0.6B/*",
            "config.json",
            "README.md",
        ),
        route,
    )
    model_route["purpose"] = "turbo-dit-vae-text-encoder"
    return [model_route]


def _install_lipsync(variant: str) -> list[dict]:
    if variant == "mlx":
        route = select_download_route(CATALOG["latentsync-mlx-1.5"])
        selected = route["selected"]
        source = _clone_source("lipsync-mlx", selected)
        upstream = _clone_source("latentsync-upstream", selected)
        python = _ensure_runtime("latentsync-mlx", [], selected)
        requirements = source / "requirements.txt"
        if requirements.is_file():
            _run_command([
                str(python), "-m", "pip", "install", "--disable-pip-version-check",
                "--no-cache-dir", "-r", str(requirements),
            ], download_route=selected)
        _run_command([
            str(python), "-m", "pip", "install", "--disable-pip-version-check",
            "--no-cache-dir",
            "ffmpeg-python", "kornia", "imageio", "imageio-ffmpeg", "matplotlib",
            "insightface==0.7.3", "onnxruntime", "diffusers", "transformers",
            "huggingface-hub>=0.30", "safetensors",
        ], download_route=selected)

        # The MLX port imports preprocessing modules from upstream but upstream
        # is not a pip-installable project. A source-local symlink keeps imports,
        # masks and checkpoints under one stable working directory.
        upstream_package = upstream / "latentsync"
        source_package = source / "latentsync"
        if not source_package.exists():
            source_package.symlink_to(upstream_package, target_is_directory=True)

        checkpoints = source / "checkpoints"
        checkpoints.mkdir(parents=True, exist_ok=True)
        model_route = _download_local_snapshot(
            python,
            CATALOG["latentsync-mlx-1.5"],
            checkpoints,
            ("latentsync_unet.pt", "whisper/tiny.pt"),
            route,
        )

        converter = source / "scripts" / "convert_weights.py"
        converted_unet = checkpoints / "latentsync_unet_mlx.safetensors"
        converted_vae = checkpoints / "vae_mlx.safetensors"
        if not _valid_weight(converted_unet):
            _run_command([
                str(python), str(converter),
                "--unet-ckpt", str(checkpoints / "latentsync_unet.pt"),
                "--unet-output", str(converted_unet),
            ], cwd=source, download_route=selected)
        if not _valid_weight(converted_vae):
            _run_command([
                str(python), str(converter), "--convert-vae",
                "--vae-output", str(converted_vae),
            ], cwd=source, download_route=selected)
        if not LIPSYNC_RUNNER.is_file():
            raise RuntimeError(f"缺少 LatentSync 本机启动器：{LIPSYNC_RUNNER}")
        _run_command([
            str(python), str(LIPSYNC_RUNNER), "--prepare-face-model",
        ], cwd=source, download_route=selected)
        if not model_installed(CATALOG["latentsync-mlx-1.5"]):
            raise RuntimeError("LatentSync MLX 下载或转换不完整")
        model_route["purpose"] = "unet-whisper-mlx-conversion-face-landmarks"
        return [model_route]
    route = select_download_route(CATALOG["musetalk-1.5"])
    selected = route["selected"]
    source = _clone_source("lipsync-cuda", selected)
    python = _ensure_runtime("musetalk", [])
    requirements = source / "requirements.txt"
    if requirements.is_file():
        _run_command([
            str(python), "-m", "pip", "install", "--disable-pip-version-check",
            "--no-cache-dir", "-r", str(requirements),
        ], download_route=selected)
    return []


def install(component: str, variant: str = "") -> dict:
    selected, model_keys = component_variant(component, variant)
    with install_guard():
        reused_cache = all(model_installed(CATALOG[key]) for key in model_keys)
        estimate = estimate_install(component, selected)
        if not reused_cache and not estimate["enough_space"]:
            need_gib = estimate["estimated_additional_bytes"] / GIB
            free_gib = estimate["free_bytes"] / GIB
            raise RuntimeError(
                f"磁盘空间不足：{component}/{selected} 预计还需 {need_gib:.1f} GiB，"
                f"当前可用 {free_gib:.1f} GiB，且必须保留 1 GiB 安全余量。"
            )
        if reused_cache:
            routes = [{
                "selected": "cache",
                "actual": "cache",
                "model": key,
                "probes": [],
                "network_used": False,
            } for key in model_keys]
        elif component == "voice":
            routes = _install_voice(selected, model_keys)
        elif component == "music":
            routes = _install_music()
        else:
            routes = _install_lipsync(selected)
        _record_install(component, selected, model_keys)
    return {
        "ok": True,
        "action": "install",
        **estimate,
        "download_routes": routes,
        "reused_cache": reused_cache,
        "network_used": not reused_cache,
        "installed": {key: model_installed(CATALOG[key]) for key in model_keys},
        "root": str(LOCAL_AI_ROOT),
        "free_bytes": shutil.disk_usage(CONFIG.workspace).free,
    }


def _remove(path: Path) -> int:
    size = _dir_size(path)
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)
    return size


def purge(
    component: str,
    variant: str = "",
    keep_runtime: bool = False,
    confirm_explicit_user_request: bool = False,
) -> dict:
    if not confirm_explicit_user_request:
        raise RuntimeError(
            "模型永久保留策略已启用；只有用户明确要求清理时，才能设置 "
            "confirm_explicit_user_request=true"
        )
    component = str(component or "").strip().lower()
    if component == "all":
        with install_guard():
            freed = _dir_size(LOCAL_AI_ROOT)
            for child in list(LOCAL_AI_ROOT.iterdir()):
                if child != MODEL_TASK_LOCK:
                    _remove(child)
        return {"ok": True, "action": "purge", "component": "all", "freed_bytes": freed}

    selected, model_keys = component_variant(component, variant)
    freed = 0
    with install_guard():
        for key in model_keys:
            freed += _remove(_model_cache_path(CATALOG[key].model_id))
        if component == "music":
            freed += _remove(SOURCES_ROOT / "ACE-Step-1.5")
            if not keep_runtime:
                freed += _remove(RUNTIMES_ROOT / "ace-step")
        elif component == "lipsync":
            source_names = ("latentsync-mlx", "LatentSync") if selected == "mlx" else ("MuseTalk",)
            for name in source_names:
                freed += _remove(SOURCES_ROOT / name)
            if not keep_runtime:
                runtime = "latentsync-mlx" if selected == "mlx" else "musetalk"
                freed += _remove(RUNTIMES_ROOT / runtime)
        elif not keep_runtime:
            remaining_voice = any(
                model_installed(spec) for spec in CATALOG.values() if spec.component == "voice"
            )
            if not remaining_voice:
                freed += _remove(RUNTIMES_ROOT / "mlx-audio")
        _drop_install_records(component, {selected})
    return {
        "ok": True,
        "action": "purge",
        "component": component,
        "variant": selected,
        "keep_runtime": keep_runtime,
        "freed_bytes": freed,
        "status": status(),
    }


def _clear_proxy_env(env: dict[str, str]) -> None:
    for key in (
        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
        "http_proxy", "https_proxy", "all_proxy", "no_proxy",
    ):
        env.pop(key, None)


def local_environment(download_route: str = "configured") -> dict[str, str]:
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
    if download_route == "direct":
        _clear_proxy_env(env)
    elif download_route == "local-8080":
        _clear_proxy_env(env)
        env["HTTPS_PROXY"] = LOCAL_MODEL_PROXY
        env["HTTP_PROXY"] = LOCAL_MODEL_PROXY
        env["HF_HUB_DISABLE_XET"] = "1"
    elif CONFIG.proxy:
        env["HTTPS_PROXY"] = CONFIG.proxy
        env["HTTP_PROXY"] = CONFIG.proxy
        env["HF_HUB_DISABLE_XET"] = "1"
    return env


def run_isolated(args: list[str], timeout: int = 3600, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Run one model task in a child process; no shell and no resident model."""
    if not args or not Path(args[0]).exists():
        raise RuntimeError(f"本地模型运行时不存在：{args[0] if args else '(empty)'}")
    if shutil.disk_usage(CONFIG.workspace).free < MIN_FREE_RESERVE:
        raise RuntimeError("本地模型任务未启动：可用磁盘空间低于 1 GiB 安全线")
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as output:
        process = subprocess.Popen(
            args,
            cwd=str(cwd) if cwd else None,
            env=local_environment(),
            text=True,
            stdout=output,
            stderr=subprocess.STDOUT,
        )
        deadline = time.monotonic() + timeout
        while True:
            try:
                return_code = process.wait(timeout=min(1.0, max(0.1, deadline - time.monotonic())))
                break
            except subprocess.TimeoutExpired:
                if shutil.disk_usage(CONFIG.workspace).free < MIN_FREE_RESERVE:
                    process.terminate()
                    try:
                        process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                    raise RuntimeError("本地模型任务已停止：可用磁盘空间低于 1 GiB 安全线")
                if time.monotonic() >= deadline:
                    process.terminate()
                    try:
                        process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                    raise RuntimeError(f"本地模型运行超时（{timeout} 秒）")
        output.seek(0)
        log = output.read()
    if return_code != 0:
        raise RuntimeError((log or "本地模型运行失败")[-1200:].strip())
    return subprocess.CompletedProcess(args, return_code, stdout=log, stderr="")


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
        "retention_policy": "persistent_until_explicit_purge",
        "automatic_cleanup": False,
        "model_task_scheduler": "cross-process-exclusive-queue",
        "purge_requires_explicit_user_confirmation": True,
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
                "cache_path": str(_model_storage_path(spec)),
                "cache_bytes": _dir_size(_model_storage_path(spec)),
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

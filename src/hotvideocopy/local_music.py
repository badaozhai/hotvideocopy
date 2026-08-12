"""ACE-Step 1.5 music generation through a temporary local API process."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import socket
import subprocess
import time
import urllib.parse
from pathlib import Path

import httpx

from .local_models import (
    CATALOG,
    JOBS_ROOT,
    MIN_FREE_RESERVE,
    SOURCES_ROOT,
    local_environment,
    runtime_python,
    serialized_model_task,
)
from .media import probe
from .workspace import slug, sub


ACE_SOURCE = SOURCES_ROOT / "ACE-Step-1.5"
SERVER_RUNNER = Path(__file__).resolve().parents[2] / "scripts" / "local_music_server.py"
TURBO_TASK_TYPES = {"text2music", "cover", "repaint"}
SECTION_LABELS = {
    "A": "Verse",
    "B": "Chorus",
    "C": "Bridge",
    "D": "Pre-Chorus",
    "E": "Instrumental Break",
    "F": "Outro",
}


def arrange_song_lyrics(
    structure: str,
    sections: dict[str, str | list[str]],
) -> tuple[str, str]:
    """Expand an AABA/ABBA/BAB form into ACE-Step lyric section tags."""
    normalized = re.sub(r"[^A-Za-z]", "", str(structure or "")).upper()
    if not 2 <= len(normalized) <= 16 or any(symbol not in SECTION_LABELS for symbol in normalized):
        raise ValueError("歌曲结构需要是 2 到 16 位的 A-F 序列，例如 AABA、ABBA 或 BAB")
    source = {str(key).strip().upper(): value for key, value in (sections or {}).items()}
    occurrence_totals = {symbol: normalized.count(symbol) for symbol in set(normalized)}
    prepared: dict[str, list[str]] = {}
    for symbol, total in occurrence_totals.items():
        raw = source.get(symbol)
        values = raw if isinstance(raw, list) else [raw]
        cleaned = [str(value or "").strip() for value in values]
        if not cleaned or any(not value for value in cleaned):
            raise ValueError(f"歌曲结构 {normalized} 缺少 {symbol} 段歌词")
        if len(cleaned) not in {1, total}:
            raise ValueError(
                f"{symbol} 段需要提供 1 份重复歌词，或按 {total} 次出现分别提供 {total} 份歌词"
            )
        prepared[symbol] = cleaned

    seen: dict[str, int] = {}
    blocks: list[str] = []
    for symbol in normalized:
        seen[symbol] = seen.get(symbol, 0) + 1
        index = seen[symbol]
        values = prepared[symbol]
        body = values[0] if len(values) == 1 else values[index - 1]
        label = SECTION_LABELS[symbol]
        if occurrence_totals[symbol] > 1:
            label += f" {index}"
        blocks.append(f"[{label}]\n{body}")
    return normalized, "\n\n".join(blocks)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _server_command(python: Path) -> list[str]:
    if not SERVER_RUNNER.is_file():
        raise RuntimeError(f"缺少 ACE-Step 本地启动器：{SERVER_RUNNER}")
    return [str(python), str(SERVER_RUNNER)]


def _tail(path: Path, limit: int = 1200) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[-limit:]
    except OSError:
        return ""


def _require_disk_reserve(phase: str) -> int:
    free_bytes = shutil.disk_usage(ACE_SOURCE).free
    if free_bytes < MIN_FREE_RESERVE:
        raise RuntimeError(f"ACE-Step 已停止：{phase}时可用磁盘空间低于 1 GiB 安全线")
    return free_bytes


async def _wait_for_server(client: httpx.AsyncClient, base_url: str, process: subprocess.Popen, log: Path,
                           timeout: int) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _require_disk_reserve("模型启动")
        if process.poll() is not None:
            raise RuntimeError(f"ACE-Step 服务启动失败：{_tail(log)}")
        try:
            response = await client.get(f"{base_url}/health")
            if response.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        await asyncio.sleep(1.0)
    raise RuntimeError(f"ACE-Step 服务启动超时：{_tail(log)}")


def _unwrap(response: httpx.Response) -> object:
    response.raise_for_status()
    body = response.json()
    if isinstance(body, dict) and body.get("code") not in (None, 200):
        raise RuntimeError(str(body.get("error") or "ACE-Step 请求失败"))
    return body.get("data") if isinstance(body, dict) and "data" in body else body


@serialized_model_task("本地配乐生成")
async def generate(
    prompt: str,
    project_id: str,
    name: str = "",
    lyrics: str = "",
    structure: str = "",
    sections: dict[str, str | list[str]] | None = None,
    instrumental: bool = False,
    vocal_language: str = "zh",
    duration: float = 30.0,
    bpm: int | None = None,
    key_scale: str = "",
    time_signature: str = "4",
    model: str = "acestep-v15-turbo",
    thinking: bool = False,
    inference_steps: int = 8,
    seed: int = -1,
    reference_audio: str = "",
    task_type: str = "text2music",
    startup_timeout: int = 1200,
    generation_timeout: int = 1800,
) -> dict:
    description = str(prompt or "").strip()
    if not description:
        raise ValueError("缺少音乐风格描述")
    if not 10 <= float(duration) <= 600:
        raise ValueError("音乐时长需要在 10 到 600 秒之间")
    if bpm is not None and not 30 <= int(bpm) <= 300:
        raise ValueError("BPM 需要在 30 到 300 之间")
    if not 1 <= int(inference_steps) <= 200:
        raise ValueError("推理步数需要在 1 到 200 之间")
    if task_type not in TURBO_TASK_TYPES:
        supported = "、".join(sorted(TURBO_TASK_TYPES))
        raise ValueError(f"当前安装的 ACE-Step Turbo 只支持：{supported}")
    if instrumental and (str(lyrics or "").strip() or structure or sections):
        raise ValueError("纯音乐不能同时提供歌词或歌曲结构")
    if structure and str(lyrics or "").strip():
        raise ValueError("lyrics 与 structure/sections 二选一，避免重复编排")
    if bool(structure) != bool(sections):
        raise ValueError("歌曲结构需要同时提供 structure 和 sections")
    if thinking:
        raise ValueError(
            "当前未安装 ACE-Step 可选 5Hz LM；请保持 thinking=false，"
            "直接传歌词、BPM、调式和拍号，避免触发额外模型下载"
        )

    python = runtime_python(CATALOG["ace-step-1.5-turbo"].runtime)
    if not python.is_file() or not ACE_SOURCE.is_dir():
        raise RuntimeError(
            "ACE-Step 尚未安装。请先执行："
            ".venv/bin/python scripts/local_media_models.py install music"
        )

    reference = Path(reference_audio).expanduser().resolve() if reference_audio else None
    if reference and not reference.is_file():
        raise FileNotFoundError(f"找不到音乐参考音频：{reference}")
    if task_type in {"cover", "repaint"} and reference is None:
        raise ValueError(f"{task_type} 任务必须提供 reference_audio")

    normalized_structure = ""
    effective_lyrics = str(lyrics or "").strip()
    if structure and sections:
        normalized_structure, effective_lyrics = arrange_song_lyrics(structure, sections)
    if instrumental:
        effective_lyrics = "[Instrumental]"

    output = sub(project_id or "scratch", "gen", "music", f"{slug(name, 'music')}.mp3")
    model_path = ACE_SOURCE / "checkpoints" / model
    if not model_path.is_dir():
        raise RuntimeError(f"ACE-Step 模型目录不完整：{model_path}")
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    stamp = f"music_{int(time.time() * 1000)}"
    log_path = JOBS_ROOT / f"{stamp}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    route = {
        "selected": "cache",
        "actual": "cache",
        "probes": [],
        "network_used": False,
    }
    env = local_environment()
    env.update({
        "ACESTEP_API_HOST": "127.0.0.1",
        "ACESTEP_API_PORT": str(port),
        "ACESTEP_DEVICE": "mps",
        "ACESTEP_LM_BACKEND": "mlx",
        "ACESTEP_INIT_LLM": "false" if not thinking else "true",
        "ACESTEP_NO_INIT": "false",
        "ACESTEP_DOWNLOAD_SOURCE": "huggingface",
        "ACESTEP_LM_MODEL_PATH": "acestep-5Hz-lm-0.6B" if thinking else "",
        "ACESTEP_CONFIG_PATH": model,
        # Apple Silicon shares CPU and GPU memory. Upstream recommends keeping
        # the models resident; moving them between "CPU" and MPS only creates
        # extra copies and can drive macOS swap usage into double digits.
        "ACESTEP_OFFLOAD_TO_CPU": "false",
        "ACESTEP_OFFLOAD_DIT_TO_CPU": "false",
        "ACESTEP_LM_OFFLOAD_TO_CPU": "false",
        # Minimum supported native-MLX VAE tile, chosen for a 16 GB machine.
        "ACESTEP_MLX_VAE_CHUNK": "192",
        "ACESTEP_CHECKPOINTS_DIR": str(ACE_SOURCE / "checkpoints"),
        "ACESTEP_TMPDIR": str(JOBS_ROOT / "acestep_tmp"),
    })
    process: subprocess.Popen | None = None
    started = time.monotonic()
    _require_disk_reserve("任务启动")
    with log_path.open("a", encoding="utf-8") as log_handle:
        try:
            process = subprocess.Popen(
                _server_command(python),
                cwd=str(ACE_SOURCE),
                env=env,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                text=True,
            )
            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=120.0), trust_env=False) as client:
                await _wait_for_server(client, base_url, process, log_path, startup_timeout)
                payload = {
                    "prompt": description,
                    "lyrics": effective_lyrics,
                    "thinking": bool(thinking),
                    "vocal_language": vocal_language or "zh",
                    "audio_format": "mp3",
                    "model": model,
                    "audio_duration": float(duration),
                    "time_signature": str(time_signature or "4"),
                    "inference_steps": int(inference_steps),
                    "batch_size": 1,
                    "use_random_seed": int(seed) < 0,
                    "seed": int(seed),
                    "task_type": task_type,
                    "reference_audio_path": str(reference) if reference else None,
                }
                if bpm is not None:
                    payload["bpm"] = int(bpm)
                if key_scale:
                    payload["key_scale"] = key_scale
                released = _unwrap(await client.post(f"{base_url}/release_task", json=payload))
                task_id = str((released or {}).get("task_id") if isinstance(released, dict) else "")
                if not task_id:
                    raise RuntimeError(f"ACE-Step 没有返回 task_id：{released}")
                deadline = time.monotonic() + generation_timeout
                item = None
                while time.monotonic() < deadline:
                    _require_disk_reserve("音乐生成")
                    queried = _unwrap(await client.post(
                        f"{base_url}/query_result", json={"task_id_list": [task_id]}
                    ))
                    jobs = queried if isinstance(queried, list) else []
                    job = jobs[0] if jobs else {}
                    status_code = int(job.get("status") or 0)
                    if status_code == 2:
                        raise RuntimeError(str(job.get("error") or "ACE-Step 音乐生成失败"))
                    if status_code == 1:
                        raw_result = job.get("result") or "[]"
                        results = json.loads(raw_result) if isinstance(raw_result, str) else raw_result
                        item = results[0] if isinstance(results, list) and results else results
                        break
                    await asyncio.sleep(2.0)
                if not isinstance(item, dict) or not item.get("file"):
                    raise RuntimeError("ACE-Step 音乐生成超时或没有输出文件")
                file_url = urllib.parse.urljoin(base_url + "/", str(item["file"]).lstrip("/"))
                async with client.stream("GET", file_url) as response:
                    response.raise_for_status()
                    with output.open("wb") as handle:
                        async for chunk in response.aiter_bytes():
                            _require_disk_reserve("结果写入")
                            handle.write(chunk)
                if output.stat().st_size < 10_000:
                    raise RuntimeError("ACE-Step 输出音频无效")
                info = await probe(output)
                return {
                    "path": str(output),
                    "bytes": output.stat().st_size,
                    "duration": info.get("duration") or 0.0,
                    "engine": "ace-step-local",
                    "model": model,
                    "task_id": task_id,
                    "prompt": description,
                    "lyrics": effective_lyrics,
                    "structure": normalized_structure,
                    "sections": sections or {},
                    "instrumental": bool(instrumental),
                    "bpm": bpm,
                    "key_scale": key_scale,
                    "time_signature": time_signature,
                    "vocal_language": vocal_language,
                    "processing_seconds": round(time.monotonic() - started, 3),
                    "download_route": route,
                    "memory_released": True,
                    "metadata": item.get("metas") or {},
                }
        finally:
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)

#!/usr/bin/env python
"""Download the optional local SD1.5 dance-repaint models on demand."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
PROJECT = ROOT / "workspace" / "dy_7671559890300685604"
MODEL_ROOT = PROJECT / "local_models"
MANIFEST = PROJECT / "local_models_manifest.json"

# The installer checks the space needed by missing files, plus a 512 MiB margin.
RESERVE_BYTES = 512 * 1024**2

# repo, filename, local folder, expected size in bytes
HF_FILES = (
    ("Lykon/dreamshaper-8-lcm", "DreamShaper8_LCM.safetensors", "dreamshaper-8-lcm", 2133804992),
    ("Lykon/dreamshaper-8", "model_index.json", "dreamshaper-8", 642),
    ("Lykon/dreamshaper-8", "scheduler/scheduler_config.json", "dreamshaper-8", 614),
    ("Lykon/dreamshaper-8", "text_encoder/config.json", "dreamshaper-8", 724),
    ("Lykon/dreamshaper-8", "text_encoder/model.fp16.safetensors", "dreamshaper-8", 246144152),
    ("Lykon/dreamshaper-8", "tokenizer/merges.txt", "dreamshaper-8", 524619),
    ("Lykon/dreamshaper-8", "tokenizer/special_tokens_map.json", "dreamshaper-8", 472),
    ("Lykon/dreamshaper-8", "tokenizer/tokenizer_config.json", "dreamshaper-8", 737),
    ("Lykon/dreamshaper-8", "tokenizer/vocab.json", "dreamshaper-8", 1059962),
    ("Lykon/dreamshaper-8", "unet/config.json", "dreamshaper-8", 1868),
    ("Lykon/dreamshaper-8", "unet/diffusion_pytorch_model.fp16.safetensors", "dreamshaper-8", 1719125304),
    ("Lykon/dreamshaper-8", "vae/config.json", "dreamshaper-8", 756),
    ("Lykon/dreamshaper-8", "vae/diffusion_pytorch_model.fp16.safetensors", "dreamshaper-8", 167335342),
    ("lllyasviel/control_v11p_sd15_openpose", "config.json", "controlnet-openpose", 999),
    (
        "lllyasviel/control_v11p_sd15_openpose",
        "diffusion_pytorch_model.fp16.safetensors",
        "controlnet-openpose",
        722598642,
    ),
    ("h94/IP-Adapter", "models/image_encoder/config.json", "ip-adapter", 560),
    ("h94/IP-Adapter", "models/image_encoder/model.safetensors", "ip-adapter", 2528373448),
    ("h94/IP-Adapter", "models/ip-adapter-plus_sd15.safetensors", "ip-adapter", 98183288),
)

BUFFALO_URL = "https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip"
BUFFALO_FILES = (
    ("genderage.onnx", 1322532),
    ("2d106det.onnx", 5030888),
    ("det_10g.onnx", 16923827),
    ("1k3d68.onnx", 143607619),
    ("w600k_r50.onnx", 174383860),
)
INSWAPPER_URL = "https://huggingface.co/ezioruan/inswapper_128.onnx/resolve/main/inswapper_128.onnx"
INSWAPPER_PATH = Path("insightface/models/inswapper_128.onnx")
INSWAPPER_BYTES = 554253681


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def configure_network() -> None:
    try:
        from hotvideocopy.config import CONFIG
    except Exception:
        proxy = os.environ.get("HVC_PROXY") or os.environ.get("HTTPS_PROXY") or ""
        token = os.environ.get("HVC_HF_TOKEN") or os.environ.get("HF_TOKEN") or ""
    else:
        proxy = CONFIG.proxy
        token = CONFIG.hf_token
    if proxy:
        os.environ.setdefault("HTTPS_PROXY", proxy)
        os.environ.setdefault("HTTP_PROXY", proxy)
    if token:
        os.environ.setdefault("HF_TOKEN", token)
    os.environ.setdefault("HF_HOME", str(MODEL_ROOT / ".hf-cache"))
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")


def expected_path(folder: str, filename: str) -> Path:
    return MODEL_ROOT / folder / filename


def missing_bytes() -> int:
    required = sum(
        expected_size
        for _, filename, folder, expected_size in HF_FILES
        if not expected_path(folder, filename).is_file()
    )
    buffalo_dir = MODEL_ROOT / "insightface" / "models" / "buffalo_l"
    if any(not (buffalo_dir / filename).is_file() for filename, _ in BUFFALO_FILES):
        # The archive and extracted files coexist briefly during extraction.
        required += 2 * sum(expected_size for _, expected_size in BUFFALO_FILES)
    if not (MODEL_ROOT / INSWAPPER_PATH).is_file():
        required += INSWAPPER_BYTES
    return required


def download_url(url: str, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and destination.stat().st_size > 0:
        print(f"skip {destination.relative_to(ROOT)}", flush=True)
        return destination
    partial = destination.with_name(destination.name + ".part")
    if partial.exists():
        partial.unlink()
    print(f"download {url}", flush=True)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "hotvideocopy-local-model-installer"},
    )
    try:
        with urllib.request.urlopen(request) as response, partial.open("wb") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
        os.replace(partial, destination)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    return destination


def extract_buffalo(archive: Path, target: Path) -> list[Path]:
    target.mkdir(parents=True, exist_ok=True)
    extracted: list[Path] = []
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            member_path = Path(member.filename)
            if member_path.is_absolute() or ".." in member_path.parts:
                raise RuntimeError(f"不安全的压缩包路径: {member.filename}")
            destination = target / member_path.name
            if member.is_dir():
                continue
            with bundle.open(member) as source, destination.open("wb") as handle:
                shutil.copyfileobj(source, handle)
            extracted.append(destination)
    return extracted


def file_row(path: Path, source: str, filename: str) -> dict:
    return {
        "source": source,
        "filename": filename,
        "path": str(path.relative_to(ROOT)),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def write_manifest(rows: list[dict]) -> None:
    payload = {
        "profile": "apple_m1_pro_16gb_sd15_lcm_openpose_ipadapter_insightface",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "model_root": str(MODEL_ROOT.relative_to(ROOT)),
        "files": rows,
        "total_bytes": sum(row["bytes"] for row in rows),
        "install_script": str(Path("scripts/dance_local_models.py")),
    }
    MANIFEST.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(MANIFEST)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="只显示缺失文件和空间估算")
    parser.add_argument("--keep-archive", action="store_true", help="保留 buffalo_l.zip")
    args = parser.parse_args()

    required = missing_bytes()
    free = shutil.disk_usage(PROJECT).free
    print(f"missing download estimate: {required / 1024**3:.2f} GiB", flush=True)
    print(f"free space: {free / 1024**3:.2f} GiB", flush=True)
    if args.dry_run:
        for repo_id, filename, folder, _ in HF_FILES:
            if not expected_path(folder, filename).is_file():
                print(f"missing {repo_id}/{filename}", flush=True)
        buffalo_dir = MODEL_ROOT / "insightface" / "models" / "buffalo_l"
        if any(not (buffalo_dir / filename).is_file() for filename, _ in BUFFALO_FILES):
            print(f"missing {BUFFALO_URL}", flush=True)
        if not (MODEL_ROOT / INSWAPPER_PATH).is_file():
            print(f"missing {INSWAPPER_URL}", flush=True)
        return
    if free < required + RESERVE_BYTES:
        raise RuntimeError(
            f"磁盘空间不足: 预计还需 {required / 1024**3:.2f} GiB，"
            f"并预留 {RESERVE_BYTES / 1024**3:.2f} GiB；当前 {free / 1024**3:.2f} GiB"
        )

    configure_network()
    try:
        from huggingface_hub import hf_hub_download
    except ImportError as error:
        raise RuntimeError(
            "缺少 huggingface_hub，请先执行: .venv/bin/python -m pip install huggingface_hub"
        ) from error

    MODEL_ROOT.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    token = os.environ.get("HF_TOKEN") or None
    for repo_id, filename, folder, _ in HF_FILES:
        target_dir = MODEL_ROOT / folder
        target_dir.mkdir(parents=True, exist_ok=True)
        print(f"download {repo_id}/{filename}", flush=True)
        downloaded = Path(hf_hub_download(
            repo_id=repo_id,
            filename=filename,
            local_dir=target_dir,
            token=token,
        ))
        rows.append(file_row(downloaded, f"hf://{repo_id}", filename))

    buffalo_dir = MODEL_ROOT / "insightface" / "models" / "buffalo_l"
    if any(not (buffalo_dir / filename).is_file() for filename, _ in BUFFALO_FILES):
        archive = MODEL_ROOT / "insightface" / "models" / "buffalo_l.zip"
        download_url(BUFFALO_URL, archive)
        extract_buffalo(archive, buffalo_dir)
        if not args.keep_archive:
            archive.unlink()
    for filename, _ in BUFFALO_FILES:
        path = buffalo_dir / filename
        if not path.is_file():
            raise RuntimeError(f"buffalo_l 解压不完整: {path}")
        rows.append(file_row(path, BUFFALO_URL, filename))

    inswapper = MODEL_ROOT / INSWAPPER_PATH
    download_url(INSWAPPER_URL, inswapper)
    rows.append(file_row(inswapper, INSWAPPER_URL, inswapper.name))
    write_manifest(rows)


if __name__ == "__main__":
    main()

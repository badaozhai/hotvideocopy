"""工作区路径解析。

状态全在文件系统——这里只负责「project_id → 目录」和「用户给的东西 → 真实文件路径」。
不做任何 JSON 读写包装：dna.json / script.json / timeline.json 由 Claude 用内置
Read/Edit 直接改，不要为它们写工具。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .config import CONFIG

_SAFE = re.compile(r"[^\w一-鿿.-]+")


def slug(text: str, fallback: str = "proj") -> str:
    s = _SAFE.sub("_", str(text or "").strip()).strip("_.")
    return (s[:60] or fallback)


def project_dir(project_id: str, create: bool = True) -> Path:
    p = CONFIG.workspace / slug(project_id)
    if create:
        p.mkdir(parents=True, exist_ok=True)
    return p


def sub(project_id: str, *parts: str, create: bool = True) -> Path:
    p = project_dir(project_id, create=create).joinpath(*parts)
    if create:
        p.parent.mkdir(parents=True, exist_ok=True)
    return p


def resolve_video(video: str) -> Path:
    """把 video 参数解析成真实文件。

    接受三种写法：绝对/相对路径、`<project_id>` （取其 source.mp4）、
    `<project_id>/gen/clips/x.mp4` （工作区相对路径）。
    """
    raw = str(video or "").strip()
    if not raw:
        raise ValueError("缺少 video 参数")

    direct = Path(raw).expanduser()
    if direct.is_file():
        return direct.resolve()

    in_ws = (CONFIG.workspace / raw).expanduser()
    if in_ws.is_file():
        return in_ws.resolve()

    src = CONFIG.workspace / slug(raw) / "source.mp4"
    if src.is_file():
        return src.resolve()

    raise FileNotFoundError(f"找不到视频：{raw}（既不是路径，也不是含 source.mp4 的 project_id）")


def project_of(path: str | Path) -> str:
    """从文件路径反推 project_id；不在工作区内返回空串。"""
    try:
        rel = Path(path).resolve().relative_to(CONFIG.workspace)
    except (ValueError, OSError):
        return ""
    return rel.parts[0] if rel.parts else ""


def write_json(path: str | Path, data: object) -> str:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(p)


def read_json(path: str | Path, default: object = None) -> object:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default

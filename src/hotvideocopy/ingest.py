"""本地视频导入 —— 抖音下载之外的另一个入口。

手机录屏、相册导出、微信传的文件……任何来源的视频都能当源片。
后面的解构链路（scene_split / get_frames / transcribe）不关心片子从哪来。

录屏常带系统 UI（状态栏/进度条/点赞栏），会污染 OCR 和画面理解——
需要裁的话 Claude 直接 Bash 一条 ffmpeg crop，这里不包。
"""

from __future__ import annotations

import shutil
from pathlib import Path

from .media import ffmpeg_bin, probe, run
from .workspace import slug, sub, write_json

# 常见视频容器；不在列表里的也试着导（ffprobe 说了算），只是先给个直觉性拦截
_VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi", ".flv", ".ts"}


async def import_local(path: str, project_id: str = "", title: str = "") -> dict:
    src = Path(str(path or "").strip()).expanduser()
    if not src.is_file():
        raise FileNotFoundError(f"找不到文件：{path}")

    info = await probe(src)
    if not info.get("duration") or not info.get("width"):
        raise RuntimeError(f"ffprobe 读不出画面流，可能不是有效视频文件：{src}")

    pid = slug(project_id) if project_id else f"local_{slug(src.stem, 'video')}"
    out = sub(pid, "source.mp4")

    if src.resolve() == out.resolve():
        pass  # 已经在工作区里，原地登记 meta 即可
    elif src.suffix.lower() == ".mp4":
        shutil.copy2(src, out)
    else:
        # mov/mkv 等先无损 remux 成 mp4（秒级）；容器塞不进再转码（分钟级，保底）
        rc, _, err = await run(ffmpeg_bin(), "-y", "-i", str(src), "-c", "copy",
                               "-movflags", "+faststart", str(out), timeout=600)
        if rc != 0 or not out.is_file() or out.stat().st_size < 10_000:
            rc, _, err = await run(ffmpeg_bin(), "-y", "-i", str(src),
                                   "-c:v", "libx264", "-crf", "18", "-preset", "fast",
                                   "-c:a", "aac", "-movflags", "+faststart",
                                   str(out), timeout=3600)
            if rc != 0 or not out.is_file():
                out.unlink(missing_ok=True)
                raise RuntimeError(f"导入失败，remux 和转码都没成：{err[-400:]}")

    final = await probe(out)
    meta = {
        "project_id": pid,
        "platform": "local",
        "source_path": str(src),
        "title": title or src.stem,
        "bytes": out.stat().st_size,
        "file": str(out),
        **final,
    }
    write_json(sub(pid, "meta.json"), meta)
    return meta

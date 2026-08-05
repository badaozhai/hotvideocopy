"""ffmpeg / ffprobe 薄封装。

只放「参数固定、到处要用」的探测与抽帧。转码裁剪这类 Claude 直接 Bash，别往这加。
"""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

_FF_CANDIDATES = ["/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg", "ffmpeg"]
_cache: dict[str, str] = {}


def ffmpeg_bin() -> str:
    if "ffmpeg" in _cache:
        return _cache["ffmpeg"]
    for c in _FF_CANDIDATES:
        if Path(c).is_file() or shutil.which(c):
            _cache["ffmpeg"] = c
            return c
    raise RuntimeError("未找到 ffmpeg（brew install ffmpeg）")


def ffprobe_bin() -> str:
    if "ffprobe" in _cache:
        return _cache["ffprobe"]
    ff = ffmpeg_bin()
    cand = ff[:-6] + "ffprobe" if ff.endswith("ffmpeg") and "/" in ff else "ffprobe"
    _cache["ffprobe"] = cand if (Path(cand).is_file() or shutil.which(cand)) else "ffprobe"
    return _cache["ffprobe"]


async def run(*args: str, timeout: float | None = None, limit: int = 64 << 20) -> tuple[int, str, str]:
    """跑外部命令，返回 (rc, stdout, stderr)。stderr 要大 buffer——场景检测全靠它。"""
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, limit=limit
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError(f"命令超时：{args[0]}")
    return proc.returncode or 0, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")


async def probe(path: str | Path) -> dict:
    """时长 / 分辨率 / 帧率 / 码率。读不出的字段给 0，不抛。"""
    rc, out, _ = await run(
        ffprobe_bin(), "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(path), timeout=60,
    )
    if rc != 0:
        return {"duration": 0.0, "width": 0, "height": 0, "fps": 0.0}
    data = json.loads(out or "{}")
    fmt = data.get("format") or {}
    v = next((s for s in data.get("streams") or [] if s.get("codec_type") == "video"), {})
    a = next((s for s in data.get("streams") or [] if s.get("codec_type") == "audio"), {})

    fps = 0.0
    raw = str(v.get("avg_frame_rate") or v.get("r_frame_rate") or "0/1")
    if "/" in raw:
        num, _, den = raw.partition("/")
        try:
            fps = round(float(num) / float(den), 3) if float(den) else 0.0
        except (ValueError, ZeroDivisionError):
            fps = 0.0

    w, h = int(v.get("width") or 0), int(v.get("height") or 0)
    return {
        "duration": round(float(fmt.get("duration") or 0), 3),
        "width": w,
        "height": h,
        "fps": fps,
        "aspect": f"{w}:{h}" if w and h else "",
        "vcodec": v.get("codec_name") or "",
        "acodec": a.get("codec_name") or "",
        "has_audio": bool(a),
        "bitrate": int(fmt.get("bit_rate") or 0),
        "size": int(fmt.get("size") or 0),
    }


async def duration_of(path: str | Path) -> float:
    return float((await probe(path)).get("duration") or 0.0)


async def extract_frame(video: str | Path, ts: float, out: str | Path, max_width: int = 640) -> bool:
    """抽单帧。-ss 放 -i 前是关键字帧快速定位，长视频批量抽帧不这么写会慢十倍。"""
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    rc, _, _ = await run(
        ffmpeg_bin(), "-y", "-ss", f"{max(0.0, ts):.3f}", "-i", str(video),
        "-frames:v", "1", "-q:v", "3", "-vf", f"scale={max_width}:-2",
        str(out), timeout=120,
    )
    return rc == 0 and Path(out).is_file()


async def first_last_frame(video: str | Path, out_dir: str | Path, stem: str) -> tuple[str, str]:
    """抽真实首尾帧——链式生成（尾帧当下一镜首帧）和镜间咬合质检都要用。副产品，失败不抛。"""
    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    first, last = d / f"{stem}_first.png", d / f"{stem}_last.png"
    try:
        await run(ffmpeg_bin(), "-y", "-i", str(video), "-vf", r"select=eq(n\,0)",
                  "-frames:v", "1", "-q:v", "2", str(first), timeout=120)
    except RuntimeError:
        pass
    try:
        await run(ffmpeg_bin(), "-y", "-sseof", "-0.2", "-i", str(video),
                  "-frames:v", "1", "-q:v", "2", str(last), timeout=120)
    except RuntimeError:
        pass
    return (str(first) if first.is_file() else "", str(last) if last.is_file() else "")

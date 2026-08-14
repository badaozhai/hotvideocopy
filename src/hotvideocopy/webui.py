"""本地可视化界面——只读查看 workspace,不做任何编辑。

设计边界:状态全在文件系统,创作用 Claude 改文件;这里只是给人看的窗口:
- 项目列表 / meta 概览 / source·output 播放
- 分镜墙:每镜中点帧缩略图 + 时长 + 该时间段内的台词与花字(前端按时间轴对齐)
- 生成素材:gen/images 画廊、gen/clips 逐条播放、gen/tts 试听
- dna/script/timeline/storyboard 等 JSON 原文查看

    .venv/bin/python -m hotvideocopy.webui [--port 8791]

抽帧走 shots.frame_files,与 MCP 的 get_frames 共用 frames/ 缓存。
"""

from __future__ import annotations

import argparse
import mimetypes
from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from starlette.routing import Route

from .config import CONFIG
from .shots import frame_files
from .workspace import read_json

_STATIC = Path(__file__).parent / "webui.html"

# 允许直接查看的工程 JSON(白名单,别把 .env 之类漏出去)
_JSON_FILES = ("meta", "shots", "transcript", "ocr", "dna", "script",
               "timeline", "storyboard", "scene3d", "motion")


def _project_dir(pid: str) -> Path:
    """pid → 目录,并防路径穿越(pid 里塞 ../ 一律 404)。"""
    d = (CONFIG.workspace / pid).resolve()
    if not d.is_dir() or d.parent != CONFIG.workspace.resolve():
        raise FileNotFoundError(pid)
    return d


def _rel_files(d: Path, *parts: str, exts: tuple[str, ...] = ()) -> list[str]:
    sub = d.joinpath(*parts)
    if not sub.is_dir():
        return []
    out = [p for p in sub.iterdir() if p.is_file() and (not exts or p.suffix.lower() in exts)]
    return [str(p.relative_to(d)) for p in sorted(out)]


async def index(_: Request) -> FileResponse:
    return FileResponse(_STATIC, media_type="text/html")


async def projects(_: Request) -> JSONResponse:
    ws = CONFIG.workspace
    items = []
    if ws.is_dir():
        for p in ws.iterdir():
            if not p.is_dir() or p.name.startswith("."):
                continue
            meta = read_json(p / "meta.json", {}) or {}
            shots = read_json(p / "shots.json", {}) or {}
            items.append({
                "id": p.name,
                "mtime": p.stat().st_mtime,
                "title": meta.get("title") or meta.get("desc") or "",
                "duration": meta.get("duration") or shots.get("duration") or 0,
                "shot_count": shots.get("shot_count") or 0,
                "has_source": (p / "source.mp4").is_file(),
                "has_output": (p / "output.mp4").is_file(),
            })
    items.sort(key=lambda x: x["mtime"], reverse=True)
    return JSONResponse(items)


async def project_detail(request: Request) -> JSONResponse:
    d = _project_dir(request.path_params["pid"])
    return JSONResponse({
        "id": d.name,
        "meta": read_json(d / "meta.json", {}) or {},
        "shots": read_json(d / "shots.json", {}) or {},
        "transcript": read_json(d / "transcript.json", {}) or {},
        "ocr": read_json(d / "ocr.json", {}) or {},
        "json_files": {n: (d / f"{n}.json").is_file() for n in _JSON_FILES},
        "has_source": (d / "source.mp4").is_file(),
        "has_output": (d / "output.mp4").is_file(),
        "gen_images": _rel_files(d, "gen", "images", exts=(".png", ".jpg", ".jpeg", ".webp")),
        "gen_clips": _rel_files(d, "gen", "clips", exts=(".mp4", ".mov", ".webm")),
        "gen_tts": _rel_files(d, "gen", "tts", exts=(".mp3", ".wav", ".m4a")),
    })


async def raw_json(request: Request) -> Response:
    name = request.path_params["name"]
    if name not in _JSON_FILES:
        return PlainTextResponse("not allowed", status_code=403)
    f = _project_dir(request.path_params["pid"]) / f"{name}.json"
    if not f.is_file():
        return PlainTextResponse("not found", status_code=404)
    return Response(f.read_text(encoding="utf-8"), media_type="application/json")


async def frame(request: Request) -> Response:
    """按时间点出缩略图,与 get_frames 共用 frames/ 缓存,重复请求不重抽。"""
    pid = request.path_params["pid"]
    _project_dir(pid)
    try:
        ts = float(request.query_params.get("t", "0"))
        width = min(1080, max(120, int(request.query_params.get("w", "320"))))
    except ValueError:
        return PlainTextResponse("bad params", status_code=400)
    got = await frame_files(pid, [ts], width)
    if not got:
        return PlainTextResponse("no frame", status_code=404)
    return FileResponse(got[0][1], media_type="image/jpeg",
                        headers={"Cache-Control": "max-age=86400"})


async def media(request: Request) -> Response:
    d = _project_dir(request.path_params["pid"])
    f = (d / request.path_params["path"]).resolve()
    if not f.is_file() or not f.is_relative_to(d):
        return PlainTextResponse("not found", status_code=404)
    mime = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
    return FileResponse(f, media_type=mime)


async def _not_found(_: Request, exc: Exception) -> PlainTextResponse:
    return PlainTextResponse(f"not found: {exc}", status_code=404)


app = Starlette(exception_handlers={FileNotFoundError: _not_found}, routes=[
    Route("/", index),
    Route("/api/projects", projects),
    Route("/api/project/{pid}", project_detail),
    Route("/api/project/{pid}/json/{name}", raw_json),
    Route("/api/project/{pid}/frame", frame),
    Route("/media/{pid}/{path:path}", media),
])


def main() -> None:
    ap = argparse.ArgumentParser(description="hotvideocopy 可视化界面(只读)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8791)
    args = ap.parse_args()
    print(f"workspace: {CONFIG.workspace}")
    print(f"打开 http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()

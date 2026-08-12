"""本地配音工作台。

启动后提供一个同源单页面应用，API Key 只留在本地 Python 进程中，
生成的音频沿用 hotvideocopy 的 workspace 目录约定。
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import binascii
import json
import mimetypes
import os
import re
import threading
import urllib.parse
import uuid
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx

from .config import CONFIG, auth_headers
from . import local_models
from .speech import tts
from .workspace import slug


ROOT = Path(__file__).resolve().parents[2]
WEB_ROOT = ROOT / "web"
ASSET_ROOT = ROOT / "assets"
WORKSPACE = CONFIG.workspace.resolve()
MAX_TEXT_LENGTH = 12000
MAX_VOICE_REFERENCE_BYTES = 25 * 1024 * 1024
REPLICA_ID = "dy_7671559890300685604"
MODEL_JOB_LOCK = threading.Lock()
MODEL_JOBS: dict[str, dict] = {}


def _json_bytes(data: object) -> bytes:
    return json.dumps(data, ensure_ascii=False).encode("utf-8")


def _relative_workspace_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(WORKSPACE).as_posix()
    except ValueError as exc:
        raise ValueError("生成文件不在工作区内") from exc


def _audio_path(file_ref: str) -> Path:
    raw = str(file_ref or "").strip()
    if not raw:
        raise FileNotFoundError("缺少音频文件")
    candidate = (WORKSPACE / raw).resolve()
    try:
        candidate.relative_to(WORKSPACE)
    except ValueError as exc:
        raise FileNotFoundError("音频文件路径无效") from exc
    if candidate.suffix.lower() not in {".mp3", ".wav", ".m4a", ".ogg", ".flac"} or not candidate.is_file():
        raise FileNotFoundError("找不到音频文件")
    return candidate


def _media_path(file_ref: str) -> Path:
    """只允许读取当前项目工作区或仓库 assets 里的媒体文件。"""
    raw = urllib.parse.unquote(str(file_ref or "").strip()).lstrip("/")
    if not raw:
        raise FileNotFoundError("缺少媒体文件")
    candidates = [(WORKSPACE / raw).resolve(), (ROOT / raw).resolve()]
    allowed_roots = (WORKSPACE, ASSET_ROOT.resolve())
    for candidate in candidates:
        try:
            if not candidate.is_file():
                continue
            if not any(candidate == root or root in candidate.parents for root in allowed_roots):
                continue
            if candidate.suffix.lower() not in {
                ".mp4", ".m4a", ".mov", ".webm", ".mp3", ".wav", ".jpg", ".jpeg", ".png", ".webp"
            }:
                continue
            return candidate
        except OSError:
            continue
    raise FileNotFoundError("找不到媒体文件")


def _save_voice_reference(payload: dict) -> dict:
    filename = Path(str(payload.get("filename") or "reference.wav")).name
    suffix = Path(filename).suffix.lower()
    if suffix not in {".wav", ".mp3", ".m4a", ".ogg", ".flac"}:
        raise ValueError("参考音频只支持 WAV、MP3、M4A、OGG 或 FLAC")
    encoded = str(payload.get("data") or "")
    if encoded.startswith("data:"):
        _, separator, encoded = encoded.partition(",")
        if not separator:
            raise ValueError("参考音频格式无效")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("参考音频编码无效") from exc
    if not raw or len(raw) > MAX_VOICE_REFERENCE_BYTES:
        raise ValueError("参考音频需要在 25 MB 以内")
    project_id = slug(str(payload.get("project_id") or "scratch"), "scratch")
    target_dir = WORKSPACE / project_id / "references" / "voice"
    target_dir.mkdir(parents=True, exist_ok=True)
    stem = slug(Path(filename).stem, "reference")
    target = target_dir / f"{stem}_{uuid.uuid4().hex[:8]}{suffix}"
    target.write_bytes(raw)
    relative = _relative_workspace_path(target)
    return {
        "ok": True,
        "file": relative,
        "bytes": len(raw),
        "name": filename,
        "audio_url": "/api/audio?file=" + urllib.parse.quote(relative),
    }


def _run_model_job(job_id: str, action: str, component: str, variant: str, keep_runtime: bool) -> None:
    try:
        if action == "install":
            result = local_models.install(component, variant)
        else:
            raise ValueError("配音工作台只允许安装模型")
        state = "done"
        error = ""
    except Exception as exc:
        result = None
        state = "failed"
        error = str(exc)
    with MODEL_JOB_LOCK:
        MODEL_JOBS[job_id].update({
            "status": state,
            "result": result,
            "error": error,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
        })


def _start_model_job(payload: dict) -> dict:
    action = str(payload.get("action") or "").strip().lower()
    component = str(payload.get("component") or "voice").strip().lower()
    variant = str(payload.get("variant") or "").strip().lower()
    keep_runtime = bool(payload.get("keep_runtime"))
    if action != "install":
        raise ValueError("配音工作台只允许安装模型；已安装模型会永久保留")
    if component not in {"voice", "music", "lipsync"}:
        raise ValueError("未知模型组件")
    with MODEL_JOB_LOCK:
        if any(job.get("status") == "running" for job in MODEL_JOBS.values()):
            raise ValueError("已有模型安装任务正在进行")
        job_id = uuid.uuid4().hex
        job = {
            "id": job_id,
            "status": "running",
            "action": action,
            "component": component,
            "variant": variant,
            "started_at": datetime.now().isoformat(timespec="seconds"),
        }
        MODEL_JOBS[job_id] = job
    thread = threading.Thread(
        target=_run_model_job,
        args=(job_id, action, component, variant, keep_runtime),
        daemon=True,
    )
    thread.start()
    return {"ok": True, "job": job}


def _replica_template() -> dict:
    """源片的逐帧动作节拍，前端和后端共用同一份真实时间轴。"""
    return {
        "ok": True,
        "project_id": REPLICA_ID,
        "title": "云霄往事 · 魔性舞步",
        "duration": 478 / 30,
        "fps": 30,
        "frame_count": 478,
        "width": 1254,
        "height": 720,
        "source_file": f"{REPLICA_ID}/source.mp4",
        "bgm_file": f"{REPLICA_ID}/bgm_original.m4a",
        "output_file": f"{REPLICA_ID}/final_wukong_change_dance_pose_driven.mp4",
        "source_title": "云霄往事之魔性舞步 镇压全场",
        "characters": {
            "male": {"name": "孙悟空", "asset": "assets/characters/wukong.png"},
            "female": {"name": "嫦娥", "asset": "assets/characters/change.png"},
        },
        "beats": [
            {"index": 1, "start_frame": 0, "end_frame": 25, "start": 0 / 30, "end": 25 / 30, "label": "起势抬袖", "cast": "female", "role": "嫦娥", "visual": "start"},
            {"index": 2, "start_frame": 25, "end_frame": 52, "start": 25 / 30, "end": 52 / 30, "label": "左右摆袖", "cast": "female", "role": "嫦娥", "visual": "female"},
            {"index": 3, "start_frame": 52, "end_frame": 79, "start": 52 / 30, "end": 79 / 30, "label": "回身落步", "cast": "female", "role": "嫦娥", "visual": "female"},
            {"index": 4, "start_frame": 79, "end_frame": 107, "start": 79 / 30, "end": 107 / 30, "label": "袖摆卡点", "cast": "female", "role": "嫦娥", "visual": "female"},
            {"index": 5, "start_frame": 107, "end_frame": 137, "start": 107 / 30, "end": 137 / 30, "label": "转身定格", "cast": "female", "role": "嫦娥", "visual": "female"},
            {"index": 6, "start_frame": 137, "end_frame": 167, "start": 137 / 30, "end": 167 / 30, "label": "侧身舒展", "cast": "female", "role": "嫦娥", "visual": "female"},
            {"index": 7, "start_frame": 167, "end_frame": 196, "start": 167 / 30, "end": 196 / 30, "label": "孙悟空入画", "cast": "male", "role": "孙悟空", "visual": "approach"},
            {"index": 8, "start_frame": 196, "end_frame": 224, "start": 196 / 30, "end": 224 / 30, "label": "双人靠近", "cast": "duo", "role": "孙悟空 × 嫦娥", "visual": "approach"},
            {"index": 9, "start_frame": 224, "end_frame": 254, "start": 224 / 30, "end": 254 / 30, "label": "对望抬手", "cast": "duo", "role": "孙悟空 × 嫦娥", "visual": "interaction"},
            {"index": 10, "start_frame": 254, "end_frame": 284, "start": 254 / 30, "end": 284 / 30, "label": "正面互动", "cast": "duo", "role": "孙悟空 × 嫦娥", "visual": "interaction"},
            {"index": 11, "start_frame": 284, "end_frame": 316, "start": 284 / 30, "end": 316 / 30, "label": "手势对拍", "cast": "duo", "role": "孙悟空 × 嫦娥", "visual": "interaction"},
            {"index": 12, "start_frame": 316, "end_frame": 346, "start": 316 / 30, "end": 346 / 30, "label": "近景碰拍", "cast": "duo", "role": "孙悟空 × 嫦娥", "visual": "interaction"},
            {"index": 13, "start_frame": 346, "end_frame": 377, "start": 346 / 30, "end": 377 / 30, "label": "交错转身", "cast": "duo", "role": "孙悟空 × 嫦娥", "visual": "interaction"},
            {"index": 14, "start_frame": 377, "end_frame": 407, "start": 377 / 30, "end": 407 / 30, "label": "嫦娥下探", "cast": "duo", "role": "孙悟空 × 嫦娥", "visual": "exit"},
            {"index": 15, "start_frame": 407, "end_frame": 436, "start": 407 / 30, "end": 436 / 30, "label": "嫦娥退场", "cast": "female", "role": "嫦娥", "visual": "exit"},
            {"index": 16, "start_frame": 436, "end_frame": 478, "start": 436 / 30, "end": 478 / 30, "label": "悟空收尾", "cast": "male", "role": "孙悟空", "visual": "finish"},
        ],
    }


def _replica_project() -> dict:
    data = _replica_template()
    path = WORKSPACE / REPLICA_ID / "replication.json"
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(saved, dict):
            data.update(saved)
            data["ok"] = True
    except (OSError, ValueError, TypeError):
        pass
    return data


def _chat_endpoint() -> str:
    base = str(CONFIG.base_url or "").strip().rstrip("/")
    if not base:
        raise RuntimeError("未配置 AI 网关")
    if re.search(r"/v\d+$", base):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


def _local_polish(text: str, style: str) -> str:
    """没有 AI Key 时也能把常见标点变成可听见的停顿。"""
    value = re.sub(r"[ \t]+", " ", str(text or "").strip())
    value = re.sub(r"(?<!\])([。！？!?])(?!(?:\[停顿))", r"\1[停顿=0.4s]", value)
    value = re.sub(r"(?<!\])([，,；;])(?!(?:\[停顿))", r"\1[停顿=0.16s]", value)
    if style == "活泼" and value and not value.startswith("[活泼]"):
        value = f"[活泼]{value}[/活泼]"
    elif style == "沉稳" and value and not value.startswith("[沉稳]"):
        value = f"[沉稳]{value}[/沉稳]"
    return value


async def _polish_script(text: str, style: str) -> tuple[str, str]:
    """优先调用已配置的 OpenAI 兼容网关，失败时退回本地规则。"""
    fallback = _local_polish(text, style)
    if not CONFIG.base_url or not CONFIG.api_key:
        return fallback, "local"
    prompt = (
        "你是中文短视频配音导演。保留原台词事实、人物口吻和句子顺序，只做适合口播的轻微断句，"
        "并用标签标出语气。可用标签只有：[停顿=0.2s]、[停顿=0.5s]、[强调]文字[/强调]、"
        "[轻声]文字[/轻声]、[温柔]文字[/温柔]、[活泼]文字[/活泼]、[沉稳]文字[/沉稳]。"
        "不要解释，不要 Markdown，不要添加新信息。"
    )
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, read=60.0),
                                     proxy=CONFIG.proxy or None) as client:
            resp = await client.post(_chat_endpoint(), headers=auth_headers(CONFIG.api_key), json={
                "model": os.environ.get("HVC_TEXT_MODEL", "gpt-4o-mini"),
                "temperature": 0.35,
                "messages": [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": f"语气偏好：{style or '自然'}\n\n原台词：\n{text}"},
                ],
            })
        if resp.status_code != 200:
            return fallback, "local"
        body = resp.json()
        content = body["choices"][0]["message"]["content"]
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        cleaned = re.sub(r"^\x60\x60\x60(?:text)?|\x60\x60\x60$", "", str(content or "").strip(), flags=re.I).strip()
        return (cleaned or fallback), "ai"
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
        return fallback, "local"


class Handler(BaseHTTPRequestHandler):
    server_version = "hotvideocopy-web/0.1"

    def log_message(self, fmt: str, *args) -> None:
        # 保留轻量访问日志，避免静态资源请求刷屏。
        if self.path.startswith("/api/"):
            super().log_message(fmt, *args)

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, data: object) -> None:
        self._send(status, _json_bytes(data), "application/json; charset=utf-8")

    def _send_media(self, path: Path) -> None:
        body = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        range_header = self.headers.get("Range", "")
        start, end = 0, len(body) - 1
        status = 200
        if range_header.startswith("bytes="):
            raw_range = range_header.removeprefix("bytes=").split(",", 1)[0].strip()
            raw_start, _, raw_end = raw_range.partition("-")
            try:
                if raw_start:
                    start = int(raw_start)
                    end = int(raw_end) if raw_end else end
                elif raw_end:
                    start = max(0, len(body) - int(raw_end))
                if start < 0 or start >= len(body) or end < start:
                    raise ValueError
                end = min(end, len(body) - 1)
                status = 206
            except ValueError:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{len(body)}")
                self.end_headers()
                return
        chunk = body[start:end + 1]
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(chunk)))
        self.send_header("Accept-Ranges", "bytes")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(body)}")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(chunk)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/health":
            self._send_json(200, {"ok": True, "workspace": WORKSPACE.name})
            return
        if parsed.path == "/api/local-models":
            self._send_json(200, {"ok": True, **local_models.status()})
            return
        if parsed.path == "/api/local-model-job":
            query = urllib.parse.parse_qs(parsed.query)
            job_id = query.get("id", [""])[0]
            with MODEL_JOB_LOCK:
                job = dict(MODEL_JOBS.get(job_id) or {})
            if not job:
                self._send_json(404, {"ok": False, "error": "找不到模型任务"})
            else:
                self._send_json(200, {"ok": True, "job": job})
            return
        if parsed.path == "/api/audio":
            try:
                query = urllib.parse.parse_qs(parsed.query)
                path = _audio_path(query.get("file", [""])[0])
                body = path.read_bytes()
            except (FileNotFoundError, OSError, ValueError) as exc:
                self._send_json(404, {"ok": False, "error": str(exc)})
                return
            mime = mimetypes.guess_type(path.name)[0] or "audio/mpeg"
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Disposition", f'inline; filename="{path.name}"')
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/api/media":
            try:
                query = urllib.parse.parse_qs(parsed.query)
                path = _media_path(query.get("file", [""])[0])
                self._send_media(path)
            except (FileNotFoundError, OSError, ValueError) as exc:
                self._send_json(404, {"ok": False, "error": str(exc)})
            return
        if parsed.path == "/api/replica":
            self._send_json(200, _replica_project())
            return
        self._serve_static(parsed.path)

    def _serve_static(self, url_path: str) -> None:
        relative = urllib.parse.unquote(url_path.lstrip("/")) or "index.html"
        candidate = (WEB_ROOT / relative).resolve()
        try:
            candidate.relative_to(WEB_ROOT.resolve())
        except ValueError:
            self._send_json(404, {"ok": False, "error": "页面不存在"})
            return
        if not candidate.is_file():
            candidate = WEB_ROOT / "index.html"
        try:
            body = candidate.read_bytes()
        except OSError:
            self._send_json(404, {"ok": False, "error": "页面不存在"})
            return
        mime = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        charset = "; charset=utf-8" if mime.startswith(("text/", "application/javascript")) else ""
        self._send(200, body, mime + charset)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/voice-reference":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 36_000_000:
                    raise ValueError("参考音频请求无效")
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                self._send_json(200, _save_voice_reference(payload))
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                self._send_json(400, {"ok": False, "error": str(exc)})
            except OSError as exc:
                self._send_json(500, {"ok": False, "error": f"保存参考音频失败：{exc}"})
            return
        if parsed.path == "/api/local-models/action":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 100_000:
                    raise ValueError("模型操作请求无效")
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                self._send_json(202, _start_model_job(payload))
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                self._send_json(400, {"ok": False, "error": str(exc)})
            return
        if parsed.path == "/api/polish":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 1_000_000:
                    raise ValueError("请求内容无效")
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                text = str(payload.get("text", "")).strip()
                if not text:
                    raise ValueError("请输入需要处理的台词")
                if len(text) > MAX_TEXT_LENGTH:
                    raise ValueError(f"台词不能超过 {MAX_TEXT_LENGTH} 字")
                polished, engine = asyncio.run(_polish_script(text, str(payload.get("style", "自然"))))
                self._send_json(200, {"ok": True, "text": polished, "engine": engine})
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                self._send_json(400, {"ok": False, "error": str(exc)})
            except Exception as exc:
                self._send_json(500, {"ok": False, "error": str(exc)})
            return
        if parsed.path == "/api/replica":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 1_000_000:
                    raise ValueError("请求内容无效")
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("复刻配置格式无效")
                beats = payload.get("beats")
                if not isinstance(beats, list) or not beats:
                    raise ValueError("缺少动作时间轴")
                if len(beats) > 200:
                    raise ValueError("动作时间轴过长")
                fps = int(payload.get("fps") or 30)
                frame_count = int(payload.get("frame_count") or 0)
                if fps <= 0 or frame_count <= 0:
                    raise ValueError("帧率或总帧数无效")
                expected_start = 0
                for beat in beats:
                    start_frame = int(beat.get("start_frame", round(float(beat["start"]) * fps)))
                    end_frame = int(beat.get("end_frame", round(float(beat["end"]) * fps)))
                    if start_frame != expected_start or end_frame <= start_frame:
                        raise ValueError("动作时间轴必须由连续整数帧组成")
                    if abs(float(beat["start"]) - start_frame / fps) > 0.00001 or abs(float(beat["end"]) - end_frame / fps) > 0.00001:
                        raise ValueError("动作时间点没有对齐帧边界")
                    beat["start_frame"] = start_frame
                    beat["end_frame"] = end_frame
                    expected_start = end_frame
                if expected_start != frame_count:
                    raise ValueError("动作时间轴末帧与总帧数不一致")
                pid = slug(str(payload.get("project_id") or REPLICA_ID), REPLICA_ID)
                project_path = WORKSPACE / pid
                project_path.mkdir(parents=True, exist_ok=True)
                data = {
                    "schema_version": "1.0",
                    "project_id": pid,
                    "source_file": str(payload.get("source_file") or f"{pid}/source.mp4"),
                    "bgm_file": str(payload.get("bgm_file") or f"{pid}/bgm_original.m4a"),
                    "fps": fps,
                    "frame_count": frame_count,
                    "duration": frame_count / fps,
                    "characters": payload.get("characters") or {
                        "male": "assets/characters/wukong.png",
                        "female": "assets/characters/change.png",
                    },
                    "beats": beats,
                    "locks": payload.get("locks") or {"frame": True, "beat": True, "audio": True},
                    "updated_at": datetime.now().isoformat(timespec="seconds"),
                }
                out = project_path / "replication.json"
                out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                self._send_json(200, {"ok": True, "project_id": pid, "file": f"workspace/{pid}/replication.json"})
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                self._send_json(400, {"ok": False, "error": str(exc)})
            except OSError as exc:
                self._send_json(500, {"ok": False, "error": f"写入复刻配置失败：{exc}"})
            return
        if parsed.path != "/api/tts":
            self._send_json(404, {"ok": False, "error": "接口不存在"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 1_000_000:
                raise ValueError("请求内容无效")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            text = str(payload.get("text", "")).strip()
            if not text:
                raise ValueError("请输入需要合成的文案")
            if len(text) > MAX_TEXT_LENGTH:
                raise ValueError(f"文案不能超过 {MAX_TEXT_LENGTH} 字")

            voice = str(payload.get("voice", "zh-CN-YunxiNeural")).strip()
            engine = str(payload.get("engine", "edge")).strip().lower()
            speed = float(payload.get("speed", 1.0))
            pitch = int(payload.get("pitch", 0))
            volume = int(payload.get("volume", 0))
            style = str(payload.get("style", "自然")).strip()
            if not 0.5 <= speed <= 2.0:
                raise ValueError("语速需要在 0.5 到 2.0 之间")
            if not -50 <= pitch <= 50 or not -50 <= volume <= 50:
                raise ValueError("音高和音量需要在 -50 到 50 之间")
            project_id = slug(str(payload.get("project_id", "scratch")), "scratch")
            name = slug(str(payload.get("name", "")), "")
            if not name:
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                name = f"narration_{stamp}_{uuid.uuid4().hex[:5]}"

            result = asyncio.run(tts(text, voice, project_id, name, speed,
                                      str(payload.get("model", "")).strip(),
                                      engine=engine, pitch=pitch, volume=volume, style=style,
                                      instruction=str(payload.get("instruction", "")).strip(),
                                      language=str(payload.get("language", "Chinese")).strip(),
                                      reference_audio=str(
                                          _audio_path(str(payload.get("reference_audio")))
                                      ) if payload.get("reference_audio") else "",
                                      reference_text=str(payload.get("reference_text", "")).strip(),
                                      consent=bool(payload.get("consent"))))
            audio_path = Path(result["path"]).resolve()
            relative = _relative_workspace_path(audio_path)
            self._send_json(200, {
                "ok": True,
                "audio_url": "/api/audio?file=" + urllib.parse.quote(relative),
                "download_url": "/api/audio?file=" + urllib.parse.quote(relative),
                "file": relative,
                "project_id": project_id,
                "voice": result.get("voice", voice),
                "engine": result.get("engine", engine),
                "speed": result.get("speed", speed),
                "pitch": result.get("pitch", pitch),
                "volume": result.get("volume", volume),
                "style": result.get("style", style),
                "instruction": result.get("instruction", payload.get("instruction", "")),
                "language": result.get("language", payload.get("language", "Chinese")),
                "model": result.get("model", payload.get("model", "")),
                "cloned": result.get("cloned", False),
                "duration": result.get("duration", 0),
                "bytes": result.get("bytes", 0),
                "created_at": datetime.now().isoformat(timespec="seconds"),
            })
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
        except Exception as exc:  # 合成器返回的异常需要直接显示给用户
            self._send_json(500, {"ok": False, "error": str(exc)})


def main() -> None:
    parser = argparse.ArgumentParser(description="启动 hotvideocopy 本地配音工作台")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--port", type=int, default=8765, help="监听端口")
    parser.add_argument("--no-open", action="store_true", help="启动后不自动打开浏览器")
    args = parser.parse_args()

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    shown_host = "127.0.0.1" if args.host in {"0.0.0.0", "::"} else args.host
    url = f"http://{shown_host}:{httpd.server_port}/"
    print(f"配音工作台已启动：{url}", flush=True)
    if not args.no_open:
        threading.Timer(0.25, webbrowser.open, args=(url,)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n配音工作台已停止", flush=True)
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()

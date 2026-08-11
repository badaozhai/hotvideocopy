"""TTS：双引擎。

1. **api** —— OpenAI 兼容 /v1/audio/speech，走网关。协议标准，但中转站要开这条路由。
2. **edge** —— edge-tts（微软 Edge 在线 TTS）。免 Key 免费，中文音色好
   （zh-CN-YunxiNeural 男口播 / zh-CN-XiaoxiaoNeural 女声），短视频旁白够用。

默认 auto：先试网关，路由不存在（404）自动落到 edge。哪天网关把 audio/speech
开了，不改任何配置自动升级回 api。

本地大模型（IndexTTS-2 / CosyVoice 2）只有「音色克隆」这一个理由值得上，
依赖太重（torch + 数 GB 权重），需求出现前不进工具箱。

返回里带 duration——排 timeline 时人声段的落点全靠它。
"""

from __future__ import annotations

import asyncio
import re
import subprocess
import tempfile
from pathlib import Path

import httpx

from .config import CONFIG, RETRIABLE_STATUS, auth_headers, require
from .images import _endpoint
from .media import probe
from .workspace import slug, sub

# OpenAI 音色名 → edge 音色的兜底映射；直接传 zh-CN-*Neural 也认
_EDGE_DEFAULT = "zh-CN-YunxiNeural"
_EDGE_MAP = {
    "alloy": "zh-CN-YunxiNeural",     # 青年男声，口播感
    "echo": "zh-CN-YunjianNeural",    # 沉稳男声
    "onyx": "zh-CN-YunyangNeural",    # 新闻男声
    "nova": "zh-CN-XiaoxiaoNeural",   # 活泼女声
    "shimmer": "zh-CN-XiaoyiNeural",  # 温柔女声
}


class _RouteMissing(RuntimeError):
    """网关没开 audio/speech 路由——auto 模式下落 edge 的信号。"""


async def tts(text: str, voice: str = "", project_id: str = "",
              name: str = "", speed: float = 1.0, model: str = "",
              max_retries: int = 3, engine: str = "", pitch: int = 0,
              volume: int = 0, style: str = "", instruction: str = "",
              language: str = "Chinese", reference_audio: str = "",
              reference_text: str = "", consent: bool = False) -> dict:
    body_text = str(text or "").strip()
    if not body_text:
        raise ValueError("缺少要合成的文本")

    out = sub(project_id or "scratch", "gen", "tts", f"{slug(name, 'line')}.mp3")
    engine = (engine or CONFIG.tts_engine or "auto").lower()
    if engine not in {"auto", "local", "api", "edge"}:
        raise ValueError("TTS 引擎只能是 auto、local、api 或 edge")

    from .local_models import CATALOG, model_installed

    local_key = "qwen3-tts-clone-8bit" if reference_audio else "qwen3-tts-custom-8bit"
    local_ready = model_installed(CATALOG[local_key])
    if engine == "local" or reference_audio or (engine == "auto" and local_ready):
        if not local_ready:
            variant = "clone" if reference_audio else "custom"
            raise RuntimeError(
                "本地高拟真语音模型尚未安装。请执行："
                f".venv/bin/python scripts/local_media_models.py install voice --variant {variant}"
            )
        from .local_voice import generate as local_generate

        tone_instruction = instruction or (
            f"使用{style or '自然'}、真实、拟人的口吻；停顿自然，不要机械播音腔。"
        )
        return await local_generate(
            body_text,
            project_id=project_id or "scratch",
            name=name or "line",
            voice=voice,
            instruction=tone_instruction,
            language=language or "Chinese",
            reference_audio=reference_audio,
            reference_text=reference_text,
            consent=consent,
            model=model if model in CATALOG else "",
            speed=speed,
        )

    if engine in ("auto", "api"):
        try:
            return await _api_tts(body_text, voice, out, speed, model, max_retries,
                                  style, pitch, volume)
        except _RouteMissing as e:
            if engine == "api":
                raise RuntimeError(str(e)) from None
            # auto：网关没这条路由，落 edge

    return await _edge_tts(body_text, voice, out, speed, pitch, volume, style)


async def _api_tts(text: str, voice: str, out, speed: float, model: str,
                   max_retries: int, style: str = "", pitch: int = 0,
                   volume: int = 0) -> dict:
    key = require(CONFIG.api_key, "API Key（HVC_API_KEY）")
    url = _endpoint(CONFIG.base_url, "audio/speech")
    model = model or CONFIG.tts_model
    voice = voice or CONFIG.tts_voice

    last_err = "TTS 失败"
    for attempt in range(1, max(1, max_retries) + 1):
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=300.0),
                                         proxy=CONFIG.proxy or None) as c:
                body = {
                    "model": model, "input": text, "voice": voice,
                    "speed": speed, "response_format": "mp3",
                }
                if style or pitch or volume:
                    body["instructions"] = (
                        f"请用{style or '自然'}的语气自然朗读，注意标点停顿；"
                        f"音高偏移 {pitch:+d} Hz，音量偏移 {volume:+d}%。"
                    )
                resp = await c.post(url, headers=auth_headers(key), json=body)
            if resp.status_code == 404:
                raise _RouteMissing(f"网关没开 audio/speech 路由（HTTP 404）：{url}")
            if resp.status_code != 200:
                last_err = f"TTS 接口报错 HTTP {resp.status_code}: {resp.text[:300]}"
                if resp.status_code in RETRIABLE_STATUS and attempt < max_retries:
                    await asyncio.sleep(1.0 * attempt)
                    continue
                raise RuntimeError(last_err)
            if len(resp.content) < 500:
                raise RuntimeError(f"TTS 返回内容异常（{len(resp.content)} 字节）")
            out.write_bytes(resp.content)
            info = await probe(out)
            return {"path": str(out), "bytes": len(resp.content), "engine": "api",
                    "model": model, "voice": voice, "speed": speed,
                    "duration": info.get("duration") or 0.0}
        except (httpx.TimeoutException, httpx.HTTPError) as e:
            last_err = f"TTS 请求失败：{e}"
            if attempt >= max_retries:
                break
            await asyncio.sleep(1.0 * attempt)

    raise RuntimeError(last_err)


def _signed(value: int, suffix: str) -> str:
    return f"{int(value):+d}{suffix}"


def _style_adjustment(style: str) -> tuple[int, int, int]:
    """返回 speed %, pitch Hz, volume % 的情绪基础偏移。"""
    return {
        "自然": (0, 0, 0),
        "温柔": (-5, -6, -8),
        "活泼": (8, 10, 8),
        "沉稳": (-6, -10, -2),
        "悬疑": (-4, -8, -4),
    }.get(str(style or "自然"), (0, 0, 0))


_PAUSE_RE = re.compile(r"\[(?:停顿|pause)\s*(?:=|：|:)\s*([0-9]+(?:\.[0-9]+)?)\s*(ms|s)?\]", re.I)
_TAGGED_TOKEN_RE = re.compile(
    r"\[(?:停顿|pause)\s*(?:=|：|:)\s*[0-9]+(?:\.[0-9]+)?\s*(?:ms|s)?\]"
    r"|\[(强调|轻声|温柔|活泼|沉稳)\](.*?)\[/\1\]",
    re.I | re.S,
)


def _pause_ms(token: str) -> int:
    match = _PAUSE_RE.fullmatch(token.strip())
    if not match:
        return 0
    amount = float(match.group(1))
    unit = (match.group(2) or "s").lower()
    return int(max(80, min(3000, amount if unit == "ms" else amount * 1000)))


def _tagged_segments(text: str, default_style: str = "") -> list[tuple[str, str, str]]:
    """拆成 text/pause 片段，供 edge-tts 分段合成以实现局部语气。"""
    segments: list[tuple[str, str, str]] = []
    cursor = 0
    for match in _TAGGED_TOKEN_RE.finditer(text):
        if match.start() > cursor:
            segments.append(("text", text[cursor:match.start()], default_style))
        if match.group(1):
            segments.append(("text", match.group(2), match.group(1)))
        else:
            segments.append(("pause", str(_pause_ms(match.group(0))), ""))
        cursor = match.end()
    if cursor < len(text):
        segments.append(("text", text[cursor:], default_style))
    return [(kind, value, tone) for kind, value, tone in segments if value]


def _pause_text(milliseconds: int) -> str:
    """Edge WebSocket TTS 不接受 break，用服务端可识别的标点保留节奏。"""
    if milliseconds <= 220:
        return "，"
    if milliseconds <= 700:
        return "……"
    return "。"


async def _edge_tts_tagged(text: str, voice: str, out, rate_value: int,
                           pitch_value: int, volume_value: int, style: str) -> None:
    """将每段 prosody 交给 Edge 服务端，再拼接服务端返回的音频。"""
    import edge_tts

    segments = _tagged_segments(text, style)
    if not any(kind == "text" and value.strip() for kind, value, _ in segments):
        raise ValueError("语气标签里没有可合成的文字")
    server_segments = []
    pending_pause = ""
    for kind, value, tone in segments:
        if kind == "pause":
            pause = _pause_text(int(value))
            if server_segments:
                previous_kind, previous_value, previous_tone = server_segments[-1]
                server_segments[-1] = (previous_kind, previous_value + pause, previous_tone)
            else:
                pending_pause += pause
        else:
            server_segments.append(("text", pending_pause + value, tone))
            pending_pause = ""
    if pending_pause and server_segments:
        kind, value, tone = server_segments[-1]
        server_segments[-1] = (kind, value + pending_pause, tone)
    normalized_segments = []
    leading_punctuation = ""
    for kind, value, tone in server_segments:
        if not re.search(r"[\w一-鿿]", value):
            if normalized_segments:
                previous_kind, previous_value, previous_tone = normalized_segments[-1]
                normalized_segments[-1] = (previous_kind, previous_value + value, previous_tone)
            else:
                leading_punctuation += value
            continue
        normalized_segments.append(("text", leading_punctuation + value, tone))
        leading_punctuation = ""
    if leading_punctuation and normalized_segments:
        kind, value, tone = normalized_segments[-1]
        normalized_segments[-1] = (kind, value + leading_punctuation, tone)

    with tempfile.TemporaryDirectory(prefix="hvc_tts_") as temp_dir:
        temp = Path(temp_dir)
        files = []
        for index, (_, value, tone) in enumerate(normalized_segments):
            part = temp / f"part_{index:03d}.mp3"
            tone_speed, tone_pitch, tone_volume = _style_adjustment(tone)
            communicate = edge_tts.Communicate(
                value.strip(), voice=voice,
                rate=_signed(max(-50, min(100, rate_value + tone_speed)), "%"),
                volume=_signed(max(-50, min(50, volume_value + tone_volume)), "%"),
                pitch=_signed(max(-50, min(50, pitch_value + tone_pitch)), "Hz"),
                proxy=CONFIG.proxy or None,
            )
            await communicate.save(str(part))
            files.append(part)

        concat = temp / "concat.txt"
        concat.write_text("\n".join(f"file '{path.as_posix()}'" for path in files), encoding="utf-8")
        subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
            "-ar", "24000", "-ac", "1", "-c:a", "libmp3lame", "-b:a", "48k", str(out),
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


async def _edge_tts(text: str, voice: str, out, speed: float,
                    pitch: int = 0, volume: int = 0, style: str = "") -> dict:
    try:
        import edge_tts
    except ImportError:
        raise RuntimeError("edge-tts 未安装（pip install edge-tts），"
                           "且网关没开 audio/speech 路由——两条 TTS 路都不通") from None

    v = str(voice or "").strip()
    if not v or v.lower() in _EDGE_MAP:
        v = _EDGE_MAP.get(v.lower(), "") or (
            CONFIG.tts_voice if "Neural" in CONFIG.tts_voice else _EDGE_DEFAULT)

    # speed 1.0 → +0%；1.15 → +15%。抖音口播常用 1.1–1.3
    speed_shift, style_pitch, style_volume = _style_adjustment(style)
    rate_value = int(round((float(speed or 1.0) - 1.0) * 100)) + speed_shift
    rate = _signed(max(-50, min(100, rate_value)), "%")
    pitch_value = max(-50, min(50, int(pitch or 0) + style_pitch))
    volume_value = max(-50, min(50, int(volume or 0) + style_volume))
    pitch_arg = _signed(pitch_value, "Hz")
    volume_arg = _signed(volume_value, "%")

    last_err = "edge-tts 合成失败"
    for attempt in range(1, 4):
        try:
            if _TAGGED_TOKEN_RE.search(text):
                await _edge_tts_tagged(text, v, out, rate_value, pitch_value, volume_value, style)
            else:
                communicate = edge_tts.Communicate(text, voice=v, rate=rate,
                                                   volume=volume_arg, pitch=pitch_arg,
                                                   proxy=CONFIG.proxy or None)
                await communicate.save(str(out))
            if out.stat().st_size < 500:
                raise RuntimeError(f"edge-tts 输出异常（{out.stat().st_size} 字节）")
            info = await probe(out)
            return {"path": str(out), "bytes": out.stat().st_size, "engine": "edge",
                    "model": "edge-tts", "voice": v, "speed": speed,
                    "pitch": pitch_value, "volume": volume_value, "style": style,
                    "duration": info.get("duration") or 0.0}
        except Exception as e:  # edge-tts 抛的异常类型很杂，网络性质的都值得重试
            last_err = f"edge-tts 合成失败：{e}"
            if attempt >= 3:
                break
            await asyncio.sleep(1.5 * attempt)

    raise RuntimeError(last_err)

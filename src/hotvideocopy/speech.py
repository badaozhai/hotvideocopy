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
              max_retries: int = 3) -> dict:
    body_text = str(text or "").strip()
    if not body_text:
        raise ValueError("缺少要合成的文本")

    out = sub(project_id or "scratch", "gen", "tts", f"{slug(name, 'line')}.mp3")
    engine = (CONFIG.tts_engine or "auto").lower()

    if engine in ("auto", "api"):
        try:
            return await _api_tts(body_text, voice, out, speed, model, max_retries)
        except _RouteMissing as e:
            if engine == "api":
                raise RuntimeError(str(e)) from None
            # auto：网关没这条路由，落 edge

    return await _edge_tts(body_text, voice, out, speed)


async def _api_tts(text: str, voice: str, out, speed: float, model: str, max_retries: int) -> dict:
    key = require(CONFIG.api_key, "API Key（HVC_API_KEY）")
    url = _endpoint(CONFIG.base_url, "audio/speech")
    model = model or CONFIG.tts_model
    voice = voice or CONFIG.tts_voice

    last_err = "TTS 失败"
    for attempt in range(1, max(1, max_retries) + 1):
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=300.0),
                                         proxy=CONFIG.proxy or None) as c:
                resp = await c.post(url, headers=auth_headers(key), json={
                    "model": model, "input": text, "voice": voice,
                    "speed": speed, "response_format": "mp3",
                })
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


async def _edge_tts(text: str, voice: str, out, speed: float) -> dict:
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
    rate = f"{int(round((float(speed or 1.0) - 1.0) * 100)):+d}%"

    last_err = "edge-tts 合成失败"
    for attempt in range(1, 4):
        try:
            await edge_tts.Communicate(text, voice=v, rate=rate,
                                       proxy=CONFIG.proxy or None).save(str(out))
            if out.stat().st_size < 500:
                raise RuntimeError(f"edge-tts 输出异常（{out.stat().st_size} 字节）")
            info = await probe(out)
            return {"path": str(out), "bytes": out.stat().st_size, "engine": "edge",
                    "model": "edge-tts", "voice": v, "speed": speed,
                    "duration": info.get("duration") or 0.0}
        except Exception as e:  # edge-tts 抛的异常类型很杂，网络性质的都值得重试
            last_err = f"edge-tts 合成失败：{e}"
            if attempt >= 3:
                break
            await asyncio.sleep(1.5 * attempt)

    raise RuntimeError(last_err)

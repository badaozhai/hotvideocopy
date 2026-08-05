"""TTS：OpenAI 兼容 /v1/audio/speech，走网关。

CLAUDE.md 里的本地路线（IndexTTS-2 / CosyVoice 2 音色克隆）依赖太重，先不进工具箱；
网关路线对 xAI TTS / OpenAI TTS 都通用。音色克隆需求起来了再加本地引擎。

返回里带 duration——排 timeline 时人声段的落点全靠它。
"""

from __future__ import annotations

import asyncio

import httpx

from .config import CONFIG, RETRIABLE_STATUS, auth_headers, require
from .images import _endpoint
from .media import probe
from .workspace import slug, sub


async def tts(text: str, voice: str = "", project_id: str = "",
              name: str = "", speed: float = 1.0, model: str = "",
              max_retries: int = 3) -> dict:
    body_text = str(text or "").strip()
    if not body_text:
        raise ValueError("缺少要合成的文本")

    key = require(CONFIG.api_key, "API Key（HVC_API_KEY）")
    url = _endpoint(CONFIG.base_url, "audio/speech")
    model = model or CONFIG.tts_model
    voice = voice or CONFIG.tts_voice
    out = sub(project_id or "scratch", "gen", "tts", f"{slug(name, 'line')}.mp3")

    last_err = "TTS 失败"
    for attempt in range(1, max(1, max_retries) + 1):
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=300.0),
                                         proxy=CONFIG.proxy or None) as c:
                resp = await c.post(url, headers=auth_headers(key), json={
                    "model": model, "input": body_text, "voice": voice,
                    "speed": speed, "response_format": "mp3",
                })
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
            return {"path": str(out), "bytes": len(resp.content), "model": model,
                    "voice": voice, "speed": speed,
                    "duration": info.get("duration") or 0.0}
        except (httpx.TimeoutException, httpx.HTTPError) as e:
            last_err = f"TTS 请求失败：{e}"
            if attempt >= max_retries:
                break
            await asyncio.sleep(1.0 * attempt)

    raise RuntimeError(last_err)

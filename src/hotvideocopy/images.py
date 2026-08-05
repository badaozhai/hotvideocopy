"""gpt-image-2 出图 / 改图（移植自 henduohao src/main/ai-write.js）。

用途：先出角色定妆图，再带着定妆图当参考给每个 shot 出首帧，然后走 grok `image` 模式
I2V —— 这是 CLAUDE.md 里选定的角色一致性主路径（可拿 1080p）。

移植时保留的三条实测结论（都是花过钱换来的）：
1. **并发闸默认 1**。中转对并发极敏感，一次多发就大面积 502「Upstream request failed」。
   串行反而总吞吐更高，因为不用重试。想快且上游扛得住再调 HVC_IMG_CONCURRENCY。
2. **重试口径分家**：5xx/429/超时/空图可重试；4xx（错参、内容策略）一次就死，
   标 no_retry 直接抛——否则一个 400 白烧六轮。
3. **grok 返回的 imgen.x.ai 是临时 URL**（xai-tmp-*），必须当场下载落盘，
   几小时后过期变黑图。
"""

from __future__ import annotations

import asyncio
import base64
import io
from pathlib import Path

import httpx

from .config import CONFIG, RETRIABLE_STATUS, auth_headers, require
from .workspace import slug, sub

# 档位 → gpt-image 画质档
QUALITY_TIER = {"1k": "low", "2k": "medium", "4k": "high"}
# 中转会忽略 quality 参数，但 prompt 里的【文字】它认——这是档位真正生效的途径
QUALITY_HINT = {
    "low": "标准清晰度，画面干净即可。",
    "medium": "高清画质，主体细节清晰、材质质感真实。",
    "high": "超高清画质，细节极其丰富，皮肤/织物/材质纹理刻画充分，边缘锐利，适合大图展示。",
}
ASPECT_WH = {"1:1": (1, 1), "4:3": (4, 3), "3:4": (3, 4), "16:9": (16, 9), "9:16": (9, 16), "21:9": (21, 9)}

_sem: asyncio.Semaphore | None = None


def _slot() -> asyncio.Semaphore:
    global _sem
    if _sem is None:
        _sem = asyncio.Semaphore(CONFIG.img_concurrency)
    return _sem


def _endpoint(base: str, tail: str) -> str:
    b = require(str(base or "").strip().rstrip("/"), "API 地址（HVC_BASE_URL）")
    if b.endswith(tail):
        return b
    if b.rsplit("/", 1)[-1].startswith("v") and b.rsplit("/", 1)[-1][1:].isdigit():
        return f"{b}/{tail}"
    return f"{b}/v1/{tail}"


def provider_size(aspect: str) -> str:
    """真 OpenAI 的 gpt-image 只认 1024²/1536×1024/1024×1536，精确比例交给提示词。"""
    aw, ah = ASPECT_WH.get(aspect, (1, 1))
    if aw >= ah * 1.15:
        return "1536x1024"
    if ah >= aw * 1.15:
        return "1024x1536"
    return "1024x1024"


def assemble_prompt(base: str, aspect: str = "", quality: str = "2k") -> str:
    tier = QUALITY_TIER.get(quality, "medium")
    parts = [str(base or "").strip()]
    if aspect:
        parts.append(f"画面为 {aspect} 比例。")
    parts.append(QUALITY_HINT[tier])
    return "\n\n".join(p for p in parts if p)


def sniff_mime(data: bytes) -> str:
    """按魔数认格式。别照扩展名猜——mime 写错上游会 400。"""
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"


def shrink(data: bytes, max_bytes: int = 2_500_000, max_side: int = 1280) -> tuple[bytes, str]:
    """参考图压缩。三视图原 PNG 2-3MB/张，三张 base64 后顶爆 body（~4MB 上限实案）。

    压到 JPEG/1280 边对锁定力零影响——grok 视频输出本来也就 ~480p。
    """
    if len(data) <= max_bytes:
        return data, sniff_mime(data)
    try:
        from PIL import Image
    except ImportError:
        return data, sniff_mime(data)
    img = Image.open(io.BytesIO(data))
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    if max(img.size) > max_side:
        r = max_side / max(img.size)
        img = img.resize((int(img.width * r), int(img.height * r)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue(), "image/jpeg"


def to_data_url(path: str | Path) -> str:
    raw = str(path)
    if raw.startswith("data:image"):
        return raw
    p = Path(raw).expanduser()
    if not p.is_file():
        raise FileNotFoundError(f"参考图不存在：{raw}")
    data, mime = shrink(p.read_bytes())
    return f"data:{mime};base64," + base64.b64encode(data).decode("ascii")


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=httpx.Timeout(60.0, read=600.0), proxy=CONFIG.proxy or None)


async def _persist(b64: str, project_id: str, name: str, ext: str = "png") -> dict:
    out = sub(project_id or "scratch", "gen", "images", f"{slug(name, 'img')}.{ext}")
    data = base64.b64decode(b64)
    out.write_bytes(data)
    return {"path": str(out), "bytes": len(data)}


async def _download_b64(url: str) -> str:
    async with _client() as c:
        r = await c.get(url, timeout=httpx.Timeout(120.0))
        if r.status_code != 200:
            raise RuntimeError(f"图片下载失败 HTTP {r.status_code}")
        return base64.b64encode(r.content).decode("ascii")


class _NoRetry(RuntimeError):
    pass


async def _take(resp: httpx.Response) -> str:
    """从响应里取图，统一成 base64。

    返回 URL 的一律当场下载——grok 的 imgen.x.ai 是临时链接（几小时后过期变黑图），
    而且我们要的是盘上文件，不是一个会烂掉的链接。
    """
    data = (resp.json() or {}).get("data") or [{}]
    item = data[0] if data else {}
    if item.get("b64_json"):
        return item["b64_json"]
    if item.get("url"):
        return await _download_b64(item["url"])
    return ""


async def generate(
    prompt: str,
    project_id: str = "",
    refs: list[str] | None = None,
    aspect: str = "9:16",
    quality: str = "2k",
    name: str = "",
    model: str = "",
    max_retries: int = 6,
) -> dict:
    """出图。给了 refs 走 /images/edits（I2I，锁角色），没给走 /images/generations（T2I）。"""
    base_prompt = str(prompt or "").strip()
    if not base_prompt:
        raise ValueError("缺少图片描述")

    model = model or CONFIG.image_model
    is_grok = model.startswith("grok")
    key = require(
        (CONFIG.grok_key or CONFIG.api_key) if is_grok else CONFIG.api_key,
        "Grok Key（HVC_GROK_KEY）" if is_grok else "API Key（HVC_API_KEY）",
    )
    refs = [r for r in (refs or []) if r]
    full_prompt = assemble_prompt(base_prompt, aspect, quality)
    name = name or f"img_{abs(hash(base_prompt)) % 10**8}"

    async with _slot():
        last_err = "出图失败"
        for attempt in range(1, max(1, max_retries) + 1):
            try:
                async with _client() as c:
                    if refs:
                        url = _endpoint(CONFIG.base_url, "images/edits")
                        if is_grok:
                            # grok 改图是 JSON（不是 multipart），images 复数数组，官方上限 3 张
                            resp = await c.post(url, headers=auth_headers(key), json={
                                "model": model, "prompt": full_prompt,
                                "images": [{"url": to_data_url(r), "type": "image_url"} for r in refs[:3]],
                                "aspect_ratio": aspect,
                            })
                        else:
                            # multipart 一次性消费，每次重试必须重建
                            files = []
                            for i, r in enumerate(refs):
                                p = Path(r).expanduser()
                                if not p.is_file():
                                    raise _NoRetry(f"参考图不存在：{r}")
                                files.append(("image[]", (f"ref_{i}.png", p.read_bytes(), "image/png")))
                            resp = await c.post(url, headers=auth_headers(key, json_body=False), files=files, data={
                                "model": model, "prompt": full_prompt, "n": "1",
                                "size": provider_size(aspect),
                                "quality": QUALITY_TIER.get(quality, "medium"),
                                "input_fidelity": "high",   # 高保真：尽量保住定妆图的脸
                                "output_format": "png",
                            })
                    else:
                        url = _endpoint(CONFIG.base_url, "images/generations")
                        body = ({"model": model, "prompt": full_prompt, "aspect_ratio": aspect}
                                if is_grok else  # grok 带 size 就 400，比例只认 aspect_ratio
                                {"model": model, "prompt": full_prompt, "n": 1,
                                 "size": provider_size(aspect),
                                 "quality": QUALITY_TIER.get(quality, "medium"),
                                 "response_format": "b64_json"})
                        resp = await c.post(url, headers=auth_headers(key), json=body)

                    if resp.status_code != 200:
                        last_err = f"图片接口报错 HTTP {resp.status_code}: {resp.text[:300]}"
                        if resp.status_code in RETRIABLE_STATUS and attempt < max_retries:
                            await asyncio.sleep(1.0 * attempt)
                            continue
                        raise _NoRetry(last_err)

                    b64 = await _take(resp)
                    if b64:
                        saved = await _persist(b64, project_id, name)
                        return {"model": model, "mode": "edits" if refs else "generations",
                                "prompt": full_prompt, **saved}

                    last_err = "图片接口未返回图片"
                    if attempt < max_retries:
                        await asyncio.sleep(1.0 * attempt)
                        continue
                    raise _NoRetry(last_err)

            except _NoRetry:
                raise RuntimeError(last_err) from None
            except (httpx.TimeoutException, httpx.HTTPError) as e:
                last_err = f"出图请求失败：{e}"
                if attempt >= max_retries:
                    break
                await asyncio.sleep(1.0 * attempt)

    raise RuntimeError(last_err)

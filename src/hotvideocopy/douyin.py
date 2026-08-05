"""抖音下载（移植自 henduohao src/main/viral.js，其源头是 cookagent media_downloader）。

不用 yt-dlp：抖音风控变得快，yt-dlp 的抖音 extractor 时灵时不灵，还要处理 cookie。
这条路径是分享页 `window._ROUTER_DATA` 解析 —— 不需要签名、不需要登录态，只要页面结构没变。

去水印的关键就一处：拿到的 play_addr 里把 `playwm` 换成 `play`。

页面结构会变。变了就是 `_ROUTER_DATA` 那段解析报错，去 iesdouyin 分享页看一眼实际结构再改
`_share_detail()`，其它部分不受影响。
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

import httpx

from .config import CONFIG
from .media import probe
from .workspace import sub, write_json

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36")
MOBILE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 "
             "(KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1")
DY_REFERER = "https://www.douyin.com/?recommend=1"
DY_SHARE_REFERER = "https://www.iesdouyin.com/"

URL_RE = re.compile(r'(https?://[^\s"<>\\^`{|}，。;！？、【】《》]+)', re.I)
TRAIL_RE = re.compile(r'[，。、！？;:"\'“”‘’》】）\]\}\s.,!?;:]+$')
VIDEO_FILE_RE = re.compile(r"\.(mp4|m4v|mov|webm|mkv|avi|flv)(?:\?|$)", re.I)
DY_ID_RE = re.compile(
    r"(?:video|note|slides)/(\d{19})"
    r"|[?&](?:modal_id|vid)=(\d{19})"
    r"|/share/(?:video|note|slides)/(\d{19})"
)
ROUTER_DATA_RE = re.compile(r"window\._ROUTER_DATA\s*=\s*([\s\S]*?)</script>", re.I)


def first_url(raw: str) -> str:
    """抖音分享出来的是一整段带文案的话，先把链接抠出来。"""
    m = URL_RE.search(str(raw or "").strip())
    return TRAIL_RE.sub("", m.group(1)) if m else ""


def detect_platform(url: str) -> str:
    host = ""
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        pass
    if any(k in host for k in ("douyin.com", "iesdouyin.com", "amemv.com")):
        return "douyin"
    if VIDEO_FILE_RE.search(url):
        return "direct_video"
    return ""


def extract_aweme_id(url: str) -> str:
    m = DY_ID_RE.search(url)
    return next((g for g in m.groups() if g), "") if m else ""


def _client(**kw) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        follow_redirects=True, timeout=httpx.Timeout(60.0, read=300.0),
        proxy=CONFIG.proxy or None, **kw,
    )


def best_video_url(detail: dict) -> str:
    """从作品详情里挑清晰度最高的地址，并去水印（playwm → play）。"""
    video = detail.get("video") or {}
    cands: list[tuple[float, str]] = []

    for item in video.get("bit_rate") or []:
        pa = item.get("play_addr") or {}
        score = float(item.get("bit_rate") or 0) + float(pa.get("data_size") or 0)
        cands += [(score, u) for u in (pa.get("url_list") or []) if u]

    for key in ("play_addr", "download_addr"):
        cands += [(0.0, u) for u in ((video.get(key) or {}).get("url_list") or []) if u]

    if not cands and (video.get("play_addr") or {}).get("uri"):
        uri = video["play_addr"]["uri"]
        cands.append((0.0, f"https://aweme.snssdk.com/aweme/v1/play/?video_id={uri}&ratio=1080p&line=0"))

    if not cands:
        raise RuntimeError("未能从抖音详情解析到视频下载地址")

    return max(cands, key=lambda x: x[0])[1].replace("playwm", "play")


async def _share_detail(aweme_id: str) -> dict:
    """分享页路径比 Web API 稳得多（后者常需签名），直接用它。"""
    async with _client(headers={"User-Agent": MOBILE_UA, "Referer": DY_SHARE_REFERER}) as c:
        r = await c.get(f"https://www.iesdouyin.com/share/video/{aweme_id}")
        html = r.text

    m = ROUTER_DATA_RE.search(html)
    if not m:
        raise RuntimeError("抖音分享页未找到 _ROUTER_DATA（页面结构可能已变，或触发了风控）")

    raw = m.group(1).strip().rstrip(";").strip()
    if not raw.startswith("{") and "{" in raw:
        raw = raw[raw.index("{"):].rstrip(";").strip()

    import json
    data = json.loads(raw)
    page = (data.get("loaderData") or {}).get("video_(id)/page") or {}
    items = (page.get("videoInfoRes") or {}).get("item_list") or []
    detail = next((x for x in items if str(x.get("aweme_id") or "") == aweme_id), None) or (items[0] if items else None)
    if not detail:
        raise RuntimeError(f"抖音分享页未解析到作品详情（aweme_id={aweme_id}，多半是作品已删或被限制）")
    return detail


async def _download(url: str, out: Path, referer: str) -> int:
    out.parent.mkdir(parents=True, exist_ok=True)
    async with _client(headers={"Accept": "*/*", "Referer": referer, "User-Agent": UA}) as c:
        async with c.stream("GET", url) as r:
            if r.status_code != 200:
                raise RuntimeError(f"下载失败 HTTP {r.status_code}")
            total = 0
            with out.open("wb") as f:
                async for chunk in r.aiter_bytes(1 << 18):
                    f.write(chunk)
                    total += len(chunk)
    if total < 10_000:
        out.unlink(missing_ok=True)
        raise RuntimeError(f"视频下载内容异常（{total} 字节，不足 10KB）")
    return total


async def fetch(url: str, project_id: str = "") -> dict:
    """下载无水印源片 + meta，落盘到 workspace/<project_id>/。

    project_id 省略时用 `dy_<aweme_id>`——同一条链接重跑会落回同一个工作区，可续跑。
    """
    raw = str(url or "").strip()
    link = first_url(raw) or raw
    if not link:
        raise ValueError("没有识别到有效视频链接")

    platform = detect_platform(link)
    normalized, title, author, aweme_id = link, "", "", ""
    referer, download_url, detail = DY_REFERER, link, {}

    if platform == "douyin":
        # v.douyin.com 短链先跟一次跳转拿到带 id 的长链
        async with _client(headers={"User-Agent": UA, "Referer": DY_REFERER}) as c:
            r = await c.get(link)
            normalized = str(r.url) or link
        aweme_id = extract_aweme_id(normalized) or extract_aweme_id(link)
        if not aweme_id:
            raise RuntimeError(f"未能从抖音链接解析 aweme_id：{normalized}")
        detail = await _share_detail(aweme_id)
        download_url = best_video_url(detail)
        title = str(detail.get("desc") or "")
        author = str((detail.get("author") or {}).get("nickname") or "")
        referer = DY_SHARE_REFERER
    elif platform == "direct_video":
        referer = DY_REFERER
    else:
        raise RuntimeError("暂只支持抖音分享链接或直接 mp4 链接（其它平台请自行下载后放进工作区）")

    pid = project_id or (f"dy_{aweme_id}" if aweme_id else f"vid_{abs(hash(link)) % 10**10}")
    out = sub(pid, "source.mp4")
    size = await _download(download_url, out, referer)

    info = await probe(out)
    stats = detail.get("statistics") or {}
    meta = {
        "project_id": pid,
        "platform": platform,
        "source_url": link,
        "normalized_url": normalized,
        "aweme_id": aweme_id,
        "title": title,
        "author": author,
        "bytes": size,
        "file": str(out),
        **info,
        "stats": {
            "digg": stats.get("digg_count"),
            "comment": stats.get("comment_count"),
            "share": stats.get("share_count"),
            "collect": stats.get("collect_count"),
            "play": stats.get("play_count"),
        },
    }
    write_json(sub(pid, "meta.json"), meta)
    return meta

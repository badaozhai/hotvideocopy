"""grok-imagine 视频生成（移植自 henduohao src/main/video-gen.js）。

**与原实现的关键差异：发起与轮询彻底分离。** 原版 generateVideo 一个调用里发起+轮询最多
12 分钟；MCP 里这么干会把会话卡死，且 Claude 中途做别的就丢了。这里拆成：

    gen_video_start(...) → request_id（立即返回）
    gen_video_get(id)    → pending / done（落盘）/ failed

任务清单（workspace/.video-jobs.json）保留了原版的「打捞」设计。原因很实在：钱已经花了，
片在上游生成着，会话断了不该变成孤儿。任何时候 `gen_video_jobs()` 都能把在途的捞回来。

移植保留的实测结论：
- `image` 与 `reference_images` 互斥；且 reference_images 档【脸漂得多】——该模式下视频
  不从首帧开始，丢了「首帧=第1帧」这个最强身份锚，还会被降级成非 1.5 模型（慢 6 倍）。
  生产走 image 单图档。这里保留 reference_images 能力但默认不用。
- aspect_ratio 恒带：单图模式会继承输入图比例，reference_images 模式【不继承】（竖图进横片出）。
- 发起 400/422 先怀疑是字段不识 → 去掉 duration/aspect 重试；bodyMin 仍 400 也别急着定罪，
  上游瞬时故障常被中转包成 400 invalid_request，退避重试。
- 状态查询返回 400/404/422 = 任务被上游终止，实测多为【内容审核拒绝】（血腥直写词）。
  软化措辞重生成，不是接口坏了。
- 输出 URL 是临时链接，拿到就得下载落盘。
"""

from __future__ import annotations

import asyncio
import base64
import time
from pathlib import Path

import httpx

from .config import CONFIG, RETRIABLE_STATUS, auth_headers, require
from .images import to_data_url
from .media import first_last_frame, probe
from .workspace import read_json, slug, sub, write_json

DONE_STATES = {"done", "completed", "succeeded", "success", "finished"}
FAIL_STATES = {"failed", "error", "cancelled", "canceled", "rejected", "expired"}


def _jobs_file() -> Path:
    CONFIG.workspace.mkdir(parents=True, exist_ok=True)
    return CONFIG.workspace / ".video-jobs.json"


def _load_jobs() -> list[dict]:
    data = read_json(_jobs_file(), [])
    return data if isinstance(data, list) else []


def _upsert(patch: dict) -> dict:
    jobs = _load_jobs()
    for i, j in enumerate(jobs):
        if j.get("request_id") == patch.get("request_id"):
            jobs[i] = {**j, **patch}
            merged = jobs[i]
            break
    else:
        merged = patch
        jobs.insert(0, patch)
    write_json(_jobs_file(), jobs[:200])   # 只留最近 200 条
    return merged


def _endpoint_on(base: str, action: str) -> str:
    b = require(str(base or "").strip().rstrip("/"), "视频 API 地址（HVC_VIDEO_BASE_URL / HVC_BASE_URL）")
    for tail in ("/videos/generations", "/videos/edits", "/videos/extensions"):
        if b.endswith(tail):
            return b[: -len(tail.split("/")[-1])] + action
    last = b.rsplit("/", 1)[-1]
    root = b if (last.startswith("v") and last[1:].isdigit()) else f"{b}/v1"
    return f"{root}/videos/{action}"


def _endpoint(action: str = "generations") -> str:
    return _endpoint_on(CONFIG.video_base_url, action)


def _status_endpoint(request_id: str) -> str:
    """状态查询端点。有的中转只代理「发起」，查询要直连 xAI（HVC_VIDEO_STATUS_BASE_URL）。"""
    base = CONFIG.video_status_base_url or CONFIG.video_base_url
    return _endpoint_on(base, "generations").rsplit("/", 1)[0] + "/" + request_id


def _pick(obj: dict, paths: list[str]) -> str:
    """宽容取值：中转直传 xAI，字段名不敢赌一种写法。"""
    for path in paths:
        cur: object = obj
        for k in path.split("."):
            if isinstance(cur, list) and k.isdigit():
                cur = cur[int(k)] if int(k) < len(cur) else None
            elif isinstance(cur, dict):
                cur = cur.get(k)
            else:
                cur = None
        if isinstance(cur, str) and cur.strip():
            return cur.strip()
    return ""


def pick_request_id(j: dict) -> str:
    return _pick(j, ["request_id", "id", "data.request_id", "data.id", "video.request_id", "video.id"])


def pick_video_url(j: dict) -> str:
    return _pick(j, ["video.url", "data.video.url", "url", "data.url", "video_url",
                     "data.video_url", "data.0.url", "output.0.url", "result.url"])


def pick_status(j: dict) -> str:
    return _pick(j, ["status", "state", "data.status", "video.status"]).lower()


def _key() -> str:
    return require(CONFIG.grok_key or CONFIG.api_key,
                   "Grok Key（HVC_GROK_KEY）——视频路由在中转是独立鉴权分组，主 Key 会 403")


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=httpx.Timeout(60.0, read=300.0), proxy=CONFIG.proxy or None)


async def start(
    prompt: str,
    project_id: str = "",
    image: str = "",
    reference_images: list[str] | None = None,
    duration: int = 0,
    aspect: str = "9:16",
    resolution: str = "",
    model: str = "",
    name: str = "",
) -> dict:
    """发起一镜生成，立即返回 request_id。不阻塞，不轮询。

    duration=0 表示自由时长（不传 duration，grok 按动作量自主定节奏，实验里比硬限更舒展）；
    传 1–15 则精确控。原片镜头常是 2.37s 这种小数——**向上取整生成，装配时再精确裁**。
    """
    prompt = str(prompt or "").strip()
    if not prompt:
        raise ValueError("缺少视频提示词")
    refs = [r for r in (reference_images or []) if r]
    if image and refs:
        raise ValueError("image 与 reference_images 互斥（同传上游 400）——锁角色请用 image 单图档")

    # 参数校验排在鉴权前：参数写错时别拿「缺 Key」把真正的问题盖掉
    key = _key()
    model = model or CONFIG.video_model

    d = int(round(float(duration or 0)))
    d = 0 if d <= 0 else max(1, min(15, d))
    aspect = "16:9" if aspect == "16:9" else "9:16"

    if refs:
        image_part: dict = {"reference_images": [{"image_url": to_data_url(r)} for r in refs[:3]]}
    elif image:
        image_part = {"image": {"image_url": to_data_url(image)}}
    else:
        image_part = {}

    body_min = {"model": model, "prompt": prompt, **image_part}
    body_full = {
        **body_min,
        **({"duration": d} if d > 0 else {}),
        "aspect_ratio": aspect,     # 恒带：reference_images 模式实测不继承输入图比例
        **({"resolution": resolution} if resolution else {}),
    }

    url = _endpoint("generations")
    last_err = "视频发起失败"
    extras = True

    async with _client() as c:
        for attempt in range(1, 5):
            try:
                resp = await c.post(url, headers=auth_headers(key),
                                    json=body_full if extras else body_min,
                                    timeout=httpx.Timeout(120.0))
                if resp.status_code != 200:
                    last_err = f"视频接口报错 HTTP {resp.status_code}: {resp.text[:300]}"
                    if resp.status_code in (400, 422) and extras:
                        extras = False   # 疑似不识 duration/aspect，去扩展字段重试
                        continue
                    if resp.status_code in RETRIABLE_STATUS and attempt < 4:
                        await asyncio.sleep(2.0 * attempt)
                        continue
                    # bodyMin 仍 4xx ≠ 请求必错：上游瞬时故障常被中转包成 400，退避再试
                    if resp.status_code in (400, 422) and attempt < 4:
                        await asyncio.sleep(15.0 * attempt)
                        continue
                    raise RuntimeError(last_err)

                j = resp.json() or {}
                req_id = pick_request_id(j)
                if req_id:
                    job = _upsert({
                        "request_id": req_id, "project_id": project_id, "kind": "generations",
                        "name": name or f"clip_{req_id[:8]}", "prompt": prompt[:200],
                        "image": str(image or (refs[0] if refs else "")),
                        "duration": d, "aspect": aspect, "model": model,
                        "status": "running", "ts": time.time(),
                    })
                    return {"request_id": req_id, "status": "running", "job": job,
                            "hint": "用 gen_video_get(request_id) 查询；别在这轮询，去干别的"}

                # 个别实现同步直接回片
                direct = pick_video_url(j)
                if direct:
                    sid = f"sync_{int(time.time() * 1000)}"
                    _upsert({"request_id": sid, "project_id": project_id, "kind": "generations",
                             "name": name or sid, "prompt": prompt[:200], "duration": d,
                             "aspect": aspect, "model": model, "status": "running", "ts": time.time()})
                    return await fetch_result(sid, remote_url=direct)

                last_err = f"发起响应里没有 request_id：{str(j)[:200]}"
                if attempt < 4:
                    await asyncio.sleep(2.0 * attempt)
                    continue
                raise RuntimeError(last_err)

            except (httpx.TimeoutException, httpx.HTTPError) as e:
                last_err = f"视频发起失败：{e}"
                if attempt >= 4:
                    break
                await asyncio.sleep(2.0 * attempt)

    raise RuntimeError(last_err)


async def get(request_id: str) -> dict:
    """查一次状态。done 就落盘，pending 就如实返回——调用方（Claude）自己决定何时再查。"""
    request_id = str(request_id or "").strip()
    if not request_id:
        raise ValueError("缺少 request_id")

    job = next((j for j in _load_jobs() if j.get("request_id") == request_id), {})
    if job.get("status") == "done" and job.get("path") and Path(job["path"]).is_file():
        return {"status": "done", "cached": True, **job}

    async with _client() as c:
        resp = await c.get(_status_endpoint(request_id), headers=auth_headers(_key()),
                           timeout=httpx.Timeout(30.0))

    if resp.status_code != 200:
        raw = f"HTTP {resp.status_code}: {resp.text[:300]}"
        if resp.status_code in RETRIABLE_STATUS:
            return {"status": "pending", "request_id": request_id, "note": f"状态查询临时失败（{raw}），稍后再查"}
        if resp.status_code in (400, 404, 422):
            # 发起被收下、状态查询却 4xx = 任务已被上游终止，实测多为内容审核拒绝
            msg = ("任务被上游终止（多为内容审核拒绝：把画面/动作里的血腥、暴力直写词软化后重生成）· " + raw)
            _upsert({"request_id": request_id, "status": "failed", "error": msg[:200], "done_at": time.time()})
            return {"status": "failed", "request_id": request_id, "error": msg}
        raise RuntimeError(raw)

    j = resp.json() or {}
    st = pick_status(j)
    url = pick_video_url(j)

    if url and (not st or st in DONE_STATES):
        return await fetch_result(request_id, remote_url=url)

    if st in FAIL_STATES:
        err = _pick(j, ["error.message", "message", "detail"]) or str(j)[:200]
        _upsert({"request_id": request_id, "status": "failed", "error": err[:200], "done_at": time.time()})
        return {"status": "failed", "request_id": request_id, "error": err}

    return {"status": "pending", "request_id": request_id, "upstream_status": st or "queued"}


async def fetch_result(request_id: str, remote_url: str) -> dict:
    """下载落盘 + 抽首尾帧。临时链接，拿到就下，别攒着。"""
    job = next((j for j in _load_jobs() if j.get("request_id") == request_id), {})
    pid = job.get("project_id") or "scratch"
    name = slug(job.get("name") or request_id, "clip")
    out = sub(pid, "gen", "clips", f"{name}.mp4")

    last_err = ""
    async with _client() as c:
        for attempt in range(1, 6):
            try:
                r = await c.get(remote_url, headers={"User-Agent": "Mozilla/5.0"},
                                timeout=httpx.Timeout(300.0), follow_redirects=True)
                if r.status_code != 200:
                    last_err = f"视频下载失败 HTTP {r.status_code}"
                    if r.status_code in RETRIABLE_STATUS and attempt < 5:
                        await asyncio.sleep(1.5 * attempt)
                        continue
                    raise RuntimeError(last_err)
                if len(r.content) < 10_000:
                    raise RuntimeError(f"视频下载内容异常（{len(r.content)} 字节，不足 10KB）")
                out.write_bytes(r.content)
                break
            except (httpx.TimeoutException, httpx.HTTPError) as e:
                last_err = f"视频下载失败：{e}"
                if attempt >= 5:
                    raise RuntimeError(last_err) from e
                await asyncio.sleep(1.5 * attempt)

    info = await probe(out)
    first, last = await first_last_frame(out, out.parent, name)
    patch = {
        "request_id": request_id, "status": "done", "path": str(out),
        "remote_url": remote_url, "seconds": info.get("duration"),
        "width": info.get("width"), "height": info.get("height"),
        "first_frame": first, "last_frame": last, "done_at": time.time(),
    }
    return {**_upsert(patch), "status": "done"}


async def transform(prompt: str, video_url: str, action: str = "extensions",
                    project_id: str = "", duration: int = 6, model: str = "", name: str = "") -> dict:
    """视频延长 / 编辑。上游要能自己下载源视频，所以必须是公网 HTTPS URL（不是本地路径）。

    超 15s 的长镜就靠这个从末帧续接。
    """
    prompt = str(prompt or "").strip()
    if not prompt:
        raise ValueError("缺少视频提示词")
    if not str(video_url or "").lower().startswith("https://"):
        raise ValueError("视频延长/编辑需要 xAI 可直接下载的公网 HTTPS 视频地址（gen_video_get 返回的 remote_url）")

    d = max(2, min(10, int(round(float(duration or 6))))) if action == "extensions" else 0
    body = {"model": model or "grok-imagine-video", "prompt": prompt,
            "video": {"url": video_url}, **({"duration": d} if d else {})}

    async with _client() as c:
        for attempt in range(1, 5):
            resp = await c.post(_endpoint(action), headers=auth_headers(_key()), json=body,
                                timeout=httpx.Timeout(120.0))
            if resp.status_code == 200:
                req_id = pick_request_id(resp.json() or {})
                if not req_id:
                    raise RuntimeError(f"{action} 响应里没有 request_id")
                job = _upsert({"request_id": req_id, "project_id": project_id, "kind": action,
                               "name": name or f"{action}_{req_id[:8]}", "prompt": prompt[:200],
                               "source_url": video_url, "duration": d, "status": "running", "ts": time.time()})
                return {"request_id": req_id, "status": "running", "job": job}
            if resp.status_code in RETRIABLE_STATUS and attempt < 4:
                await asyncio.sleep(2.0 * attempt)
                continue
            raise RuntimeError(f"视频{action}报错 HTTP {resp.status_code}: {resp.text[:300]}")

    raise RuntimeError(f"视频{action}发起失败")


def jobs(project_id: str = "", only_running: bool = False) -> list[dict]:
    out = _load_jobs()
    if project_id:
        out = [j for j in out if j.get("project_id") == project_id]
    if only_running:
        out = [j for j in out if j.get("status") == "running"]
    return out

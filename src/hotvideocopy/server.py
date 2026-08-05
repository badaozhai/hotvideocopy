"""hotvideocopy MCP server —— 单 server，FastMCP + stdio。

工具只做确定性的事。判断、创意、DNA 缝合全在 Claude 这边：
- 帧以 ImageContent 直接返回，Claude 自己看，不套 VLM
- dna.json / script.json / timeline.json 用内置 Read/Edit 改，这里不提供包装工具
- 转码、裁剪、抽音轨直接 Bash，这里不包
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer
from mcp.types import ImageContent, TextContent

from . import __version__, douyin, images, shots
from . import video as video_api  # 别直接 import video：多个工具有叫 video 的参数，会遮蔽
from .config import CONFIG
from .media import probe
from .workspace import project_of, resolve_video

mcp = MCPServer("hotvideocopy", version=__version__)


# ─────────────────────────── 第一阶段：解构链路 ───────────────────────────

@mcp.tool()
async def douyin_fetch(url: str, project_id: str = "") -> dict:
    """下载抖音无水印源片 + meta，落盘到 workspace/<project_id>/。

    url 可以直接粘抖音分享的整段文案（自动抠链接），也支持直接的 mp4 链接。
    project_id 省略时按 aweme_id 生成，同一条链接重跑会落回同一个工作区。
    产出：source.mp4 + meta.json（时长/分辨率/帧率/作者/点赞等）。
    """
    return await douyin.fetch(url, project_id)


@mcp.tool()
async def scene_split(video: str, threshold: float = 27.0, max_shots: int = 200) -> dict:
    """镜头分割 → shots.json。只给切点和时长曲线，不判断镜头的叙事功能。

    video 可以是 project_id、工作区相对路径或绝对路径。
    threshold 是 PySceneDetect ContentDetector 口径：调低切得碎，调高切得粗。
    返回里的 shot_durations 就是 DNA 的 rhythm.shot_durations；
    每个 shot 带 sample_ts（首/中/尾三点），拿去喂 get_frames 看画面。
    """
    return await shots.scene_split(video, threshold, max_shots)


@mcp.tool(structured_output=False)  # 返回的是 content block，别让它按 list 生成 output schema
async def get_frames(video: str, timestamps: list[float], max_width: int = 640) -> list:
    """抽指定时间点的帧，**直接返回图像**供查看——不要再套一层 VLM API。

    抽出来的帧缓存在 workspace/<project_id>/frames/，重复调用同一时间点不重抽。
    max_width 默认 640；要看清花字/小字可调到 1080。
    """
    batch = await shots.frame_batch(video, timestamps, max_width)
    if not batch:
        return [TextContent(type="text", text="没抽到任何帧（时间点可能超出时长，或文件损坏）")]

    out: list = [TextContent(
        type="text",
        text="帧序（与下面图像一一对应）：" + "、".join(f"#{i} t={ts:.2f}s" for i, (ts, _) in enumerate(batch)),
    )]
    out += [ImageContent(type="image", data=shots.to_b64(raw), mimeType="image/jpeg") for _, raw in batch]
    return out


@mcp.tool()
async def video_info(video: str) -> dict:
    """探测时长/分辨率/帧率/编码/有无音轨。写 DNA 的 meta 段和排装配参数都要用。"""
    path = resolve_video(video)
    return {"file": str(path), "project_id": project_of(path), **await probe(path)}


# ─────────────────────────── 生成端：图 ───────────────────────────

@mcp.tool()
async def gen_image(
    prompt: str,
    project_id: str = "",
    refs: list[str] | None = None,
    aspect: str = "9:16",
    quality: str = "2k",
    name: str = "",
    model: str = "",
) -> dict:
    """出图（gpt-image-2）。产出落 workspace/<project_id>/gen/images/。

    - 不给 refs → 文生图，用来出**角色定妆图**
    - 给 refs → 图生图（/images/edits, input_fidelity=high），带定妆图出**每镜首帧**，锁脸
    quality: 1k/2k/4k（映射 low/medium/high）。
    出图默认串行（上游对并发敏感，一次多发就大面积 502），批量出图直接连着调就行，内部会排队。
    """
    return await images.generate(prompt, project_id, refs, aspect, quality, name, model)


# ─────────────────────────── 生成端：视频 ───────────────────────────

@mcp.tool()
async def gen_video_start(
    prompt: str,
    project_id: str = "",
    image: str = "",
    reference_images: list[str] | None = None,
    duration: int = 0,
    aspect: str = "9:16",
    resolution: str = "",
    name: str = "",
    model: str = "",
) -> dict:
    """发起一镜视频生成（grok-imagine-video-1.5），**立即返回 request_id，不阻塞**。

    - image：首帧图路径 → I2V 单图档。**推荐路径**，可拿 1080p，「首帧=第1帧」是最强身份锚。
    - reference_images：参考图档，与 image 互斥，封顶 720p，且实测脸漂得多——非必要别用。
    - duration：0=自由时长（模型按动作量自主定节奏）；1–15 整数秒=精确控。
      原片镜头是 2.37s 这种小数时**向上取整**，装配时再用 ffmpeg 精确裁到 DNA 时间轴。
    - resolution：480p(默认)/720p/1080p，1080p 仅 T2V/I2V。

    发起后去干别的，隔一阵用 gen_video_get 查。生成的音轨后面整条丢弃，人声 BGM 全后期铺。
    """
    return await video_api.start(prompt, project_id, image, reference_images,
                                 duration, aspect, resolution, model, name)


@mcp.tool()
async def gen_video_get(request_id: str) -> dict:
    """查一次生成状态。done 就当场下载落盘（上游是临时链接，过期变黑片）。

    返回 status: pending / done / failed。pending 就等会儿再查，别循环打。
    failed 且提示「上游终止」的，绝大多数是内容审核——软化血腥/暴力直写词后重发。
    """
    return await video_api.get(request_id)


@mcp.tool()
async def gen_video_extend(
    prompt: str,
    video_url: str,
    project_id: str = "",
    duration: int = 6,
    name: str = "",
) -> dict:
    """从末帧续接延长（超 15s 的长镜靠这个）。

    video_url 必须是上游能下载的公网 HTTPS 地址——用 gen_video_get 返回的 remote_url，
    不是本地路径。返回 request_id，同样用 gen_video_get 查。
    """
    return await video_api.transform(prompt, video_url, "extensions", project_id, duration, name=name)


@mcp.tool()
def gen_video_jobs(project_id: str = "", only_running: bool = False) -> list[dict]:
    """列出视频任务清单（打捞用）。会话断了、Claude 重启了，在途的片用这个捞回来。"""
    return video_api.jobs(project_id, only_running)


@mcp.tool()
def workspace_info() -> dict:
    """当前配置与工作区状态。接不上 API 时先查这个。"""
    projects = sorted(p.name for p in CONFIG.workspace.glob("*") if p.is_dir()) if CONFIG.workspace.is_dir() else []
    return {
        "workspace": str(CONFIG.workspace),
        "projects": projects,
        "base_url": CONFIG.base_url or "(未设置 HVC_BASE_URL)",
        "video_base_url": CONFIG.video_base_url or "(未设置)",
        "api_key": "已设置" if CONFIG.api_key else "(未设置 HVC_API_KEY)",
        "grok_key": "已设置" if CONFIG.grok_key else "(未设置 HVC_GROK_KEY)",
        "image_model": CONFIG.image_model,
        "video_model": CONFIG.video_model,
        "img_concurrency": CONFIG.img_concurrency,
    }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()

#!/usr/bin/env python
"""装完跑一遍，确认工具链通。不联网、不烧钱。

    .venv/bin/python scripts/smoke.py

造一段 9:16 的三色块测试片（切点应落在 2s/4s），跑真 MCP stdio 握手，验证：
解构链路（切镜/抽帧/探测）+ 抖音链接解析与去水印 + grok/gpt-image 的端点与参数拼装。
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

PID = "smoke"


def build_fixture() -> Path:
    from hotvideocopy.config import CONFIG
    out = CONFIG.workspace / PID / "source.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "color=c=red:s=540x960:d=2",
        "-f", "lavfi", "-i", "color=c=blue:s=540x960:d=2",
        "-f", "lavfi", "-i", "color=c=green:s=540x960:d=2",
        "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]", "-map", "[v]",
        "-r", "30", "-pix_fmt", "yuv420p", str(out),
    ], check=True, capture_output=True)
    return out


async def check_pure() -> None:
    """纯函数：不需要网络也不需要 Key 的那些判断。"""
    from hotvideocopy import douyin, images as I, video as V
    import hotvideocopy.config as C

    assert douyin.first_url("看看这个 https://v.douyin.com/abc123/ 复制打开抖音") == "https://v.douyin.com/abc123/"
    assert douyin.detect_platform("https://www.douyin.com/video/7123456789012345678") == "douyin"
    assert douyin.extract_aweme_id("https://www.douyin.com/video/7123456789012345678") == "7123456789012345678"
    assert douyin.extract_aweme_id("https://www.douyin.com/x?modal_id=7123456789012345678") == "7123456789012345678"
    fake = {"video": {
        "play_addr": {"url_list": ["https://x/playwm/lo"]},
        "bit_rate": [{"bit_rate": 100, "play_addr": {"url_list": ["https://x/playwm/hi"], "data_size": 9}}],
    }}
    assert douyin.best_video_url(fake) == "https://x/play/hi"   # 选最高码率 + 去水印
    print("  抖音 链接解析 / 码率优选 / playwm→play 去水印  OK")

    object.__setattr__(C.CONFIG, "video_base_url", "https://api.x.ai/v1")
    assert V._endpoint("generations") == "https://api.x.ai/v1/videos/generations"
    assert V._endpoint("extensions") == "https://api.x.ai/v1/videos/extensions"
    assert V._status_endpoint("req_9") == "https://api.x.ai/v1/videos/req_9"
    object.__setattr__(C.CONFIG, "video_base_url", "https://gw.example.com")
    assert V._endpoint("generations") == "https://gw.example.com/v1/videos/generations"
    assert V.pick_request_id({"data": {"id": "r1"}}) == "r1"
    assert V.pick_video_url({"data": [{"url": "https://u"}]}) == "https://u"
    assert V.pick_status({"video": {"status": "PENDING"}}) == "pending"
    try:
        await V.start("x", image="/tmp/a.png", reference_images=["/tmp/b.png"])
        raise AssertionError("image/reference_images 互斥没挡住")
    except ValueError as e:
        assert "互斥" in str(e)
    print("  grok  端点补全 / 字段宽容拾取 / 模式互斥拦截  OK")

    assert I.provider_size("9:16") == "1024x1536"
    assert I.provider_size("16:9") == "1536x1024"
    assert I.provider_size("1:1") == "1024x1024"
    p = I.assemble_prompt("一个女孩", "9:16", "4k")
    assert "9:16 比例" in p and "细节极其丰富" in p
    assert I.sniff_mime(b"\xff\xd8\xff\xe0") == "image/jpeg"
    assert I.sniff_mime(b"\x89PNG\r\n\x1a\n") == "image/png"
    print("  gpt-image  尺寸就近映射 / 提示词拼装 / mime 魔数嗅探  OK")


async def check_stdio() -> None:
    """真 MCP 子进程 + 协议握手——和 Claude Code 拉起它的方式一致。"""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command=str(ROOT / ".venv" / "bin" / "hotvideocopy"),
        env={k: v for k, v in os.environ.items()
             if k not in ("HVC_API_KEY", "HVC_GROK_KEY", "OPENAI_API_KEY", "XAI_API_KEY")},
    )
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        info = await s.initialize()
        print(f"  server: {info.server_info.name} v{info.server_info.version or '?'}")

        tools = (await s.list_tools()).tools
        assert len(tools) == 15, [t.name for t in tools]
        print(f"  tools({len(tools)}): " + ", ".join(t.name for t in tools))

        # 本地导入：造个 .mov 走 remux 路径，产出要与 douyin_fetch 完全对齐
        mov = Path(tempfile.gettempdir()) / "hvc_smoke_upload.mov"
        subprocess.run(["ffmpeg", "-y", "-i", str(ROOT / "workspace" / PID / "source.mp4"),
                        "-c", "copy", str(mov)], check=True, capture_output=True)
        res = await s.call_tool("video_import", {"path": str(mov), "project_id": "smoke_import"})
        meta = json.loads(res.content[0].text)
        assert meta["platform"] == "local" and meta["duration"] > 5.5, meta
        assert (ROOT / "workspace" / "smoke_import" / "source.mp4").is_file()
        assert (ROOT / "workspace" / "smoke_import" / "meta.json").is_file()
        print(f"  video_import: .mov remux → {meta['duration']}s {meta['width']}x{meta['height']}")

        res = await s.call_tool("scene_split", {"video": PID})
        split = json.loads(res.content[0].text)
        assert split["shot_count"] == 3, split
        print(f"  scene_split: engine={split['engine']} shots={split['shot_count']} "
              f"durations={split['shot_durations']}")
        assert (ROOT / "workspace" / PID / "shots.json").is_file()

        ts = [t for sh in split["shots"] for t in sh["sample_ts"]]
        res = await s.call_tool("get_frames", {"video": PID, "timestamps": ts})
        kinds = [c.type for c in res.content]
        assert kinds.count("image") == 9, kinds
        assert all(len(c.data) > 500 for c in res.content if c.type == "image")
        print(f"  get_frames: {kinds.count('image')} 张 ImageContent + 1 条帧序说明")

        res = await s.call_tool("video_info", {"video": PID})
        vi = json.loads(res.content[0].text)
        assert vi["fps"] == 30.0 and vi["project_id"] == PID, vi
        print(f"  video_info: {vi['duration']}s {vi['width']}x{vi['height']} @{vi['fps']}fps")

        # 装配闭环：3 段精确裁切（1.5+1.2+1.0=3.7s）+ 正弦 BGM 铺满，验证成片规格
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=5",
                        "-ac", "2", str(ROOT / "workspace" / PID / "bgm.wav")],
                       check=True, capture_output=True)
        (ROOT / "workspace" / PID / "timeline.json").write_text(json.dumps({
            "video": [
                {"src": "source.mp4", "trim": [0.0, 1.5]},
                {"src": "source.mp4", "trim": [2.0, 3.2]},
                {"src": "source.mp4", "trim": [4.0, 5.0]},
            ],
            "audio": [{"src": "bgm.wav", "at": 0, "gain_db": -6, "loop": True}],
        }), encoding="utf-8")
        res = await s.call_tool("assemble", {"timeline_ref": PID})
        asm = json.loads(res.content[0].text)
        assert abs(asm["duration"] - 3.7) < 0.15, asm
        assert asm["has_audio"] and asm["clips"] == 3, asm
        assert (ROOT / "workspace" / PID / "output.mp4").is_file()
        print(f"  assemble: 3 段裁切拼接 + BGM 铺满 → {asm['duration']}s "
              f"{asm['width']}x{asm['height']} has_audio={asm['has_audio']}")

        # 错误路径要给人话，不能吐 traceback
        res = await s.call_tool("scene_split", {"video": "不存在的项目"})
        assert res.is_error and "找不到视频" in res.content[0].text
        res = await s.call_tool("gen_image", {"prompt": "测试"})
        assert res.is_error and "HVC_API_KEY" in res.content[0].text
        res = await s.call_tool("transcribe", {"video": PID})  # 测试片没音轨
        assert res.is_error and "音轨" in res.content[0].text
        res = await s.call_tool("video_import", {"path": "/不存在/x.mp4"})
        assert res.is_error and "找不到文件" in res.content[0].text
        res = await s.call_tool("tts", {"text": "测试"})
        assert res.is_error and "HVC_API_KEY" in res.content[0].text
        res = await s.call_tool("assemble", {"timeline_ref": "不存在的项目"})
        assert res.is_error and "timeline" in res.content[0].text
        print("  错误路径: 找不到视频 / 缺 Key / 没音轨 / 文件不存在 —— 都是人话  OK")


async def main() -> None:
    print("== 造测试片 ==")
    print("  " + str(build_fixture()))
    print("== 纯函数 ==")
    await check_pure()
    print("== MCP stdio 握手 ==")
    await check_stdio()
    print("\n=== ALL PASS ===")


if __name__ == "__main__":
    asyncio.run(main())

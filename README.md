# hotvideocopy

输入抖音 URL → 解构出结构化内容 DNA → 换皮改写 → 复刻成片。

不是 pipeline，是 **MCP 工具箱 + Claude 实时编排**。设计原则见 [CLAUDE.md](CLAUDE.md)。

## 安装

```bash
uv venv --python 3.12 .venv && uv pip install -e .
```

系统依赖：`ffmpeg`（`brew install ffmpeg`）。装完自检：

```bash
.venv/bin/python scripts/smoke.py
```

不联网、不烧钱：造一段测试片跑真 MCP stdio 握手，验证解构链路和各家接口的参数拼装。

> Python 锁 3.11–3.13。3.14 上 opencv / torch 生态 wheel 覆盖还不全，
> `scenedetect` 与后续的 ASR 依赖都会装不上。

## 配置

复制 `.env.example` 为 `.env` 填 Key，或直接在 MCP 配置的 `env` 段注入：

```json
{
  "mcpServers": {
    "hotvideocopy": {
      "command": "/Users/claw/hotvideocopy/.venv/bin/hotvideocopy",
      "env": {
        "HVC_BASE_URL": "https://your-gateway.example.com",
        "HVC_API_KEY": "sk-xxx",
        "HVC_GROK_KEY": "xai-xxx"
      }
    }
  }
}
```

⚠️ `HVC_GROK_KEY` 必须单独给：中转把 `/v1/videos/*` 挂在**独立鉴权分组**，主 Key 打过去 403。

## 工具

| 工具 | 阶段 | 说明 |
|---|---|---|
| `douyin_fetch(url)` | 解构 | 分享页 `_ROUTER_DATA` 解析 + 去水印，产出 `source.mp4` / `meta.json` |
| `scene_split(video)` | 解构 | PySceneDetect 切镜（退路 ffmpeg），产出 `shots.json` + 时长曲线 |
| `get_frames(video, ts[])` | 解构 | 返回 `ImageContent`，Claude 直接看画面 |
| `video_info(video)` | 解构 | 时长/分辨率/帧率/编码/音轨 |
| `gen_image(...)` | 生成 | gpt-image-2，无 refs=定妆图，有 refs=锁脸出首帧 |
| `gen_video_start(...)` | 生成 | grok，**发起即返回 request_id，不阻塞** |
| `gen_video_get(id)` | 生成 | 查状态，done 当场落盘（上游是临时链接） |
| `gen_video_extend(...)` | 生成 | 从末帧续接，超 15s 长镜用 |
| `gen_video_jobs()` | 运维 | 任务清单打捞——会话断了片不会变孤儿 |
| `workspace_info()` | 运维 | 配置与工作区状态自检 |

**没有** dna.json 的读写工具：那是普通文件，用内置 Read/Edit 改。
**没有** 转码/裁剪工具：直接 Bash ffmpeg。

## 典型流程

```
douyin_fetch(url)              → workspace/dy_<id>/source.mp4 + meta.json
scene_split("dy_<id>")         → shots.json，拿到 shot_durations 节奏曲线
get_frames("dy_<id>", [...])   → 看画面，认场景/人物/动作
（Claude 手写 dna.json —— 结构 + 节奏 + 每镜内容）
（Claude 手写 script.json —— 抽象成骨架，去题材，换皮重写）
gen_image(定妆图) → gen_image(每镜首帧, refs=[定妆图])
gen_video_start(image=首帧) ×N → gen_video_get 逐个收
（Claude 手写 timeline.json）→ ffmpeg 精确裁切拼接铺音
```

## 状态

- [x] 骨架 + `douyin_fetch` / `scene_split` / `get_frames`
- [x] gpt-image / grok 能力移植（自 `henduohao`）
- [ ] `transcribe`（demucs 分离人声 + faster-whisper + pyannote）
- [ ] `ocr_burned_text`（抖音花字只有 OCR 拿得到）
- [ ] `tts` / `assemble`

## 合规

复刻的合法边界在**结构与创意方法**，不在具体表达。DNA 只保留结构与节奏，
台词、画面、BGM 一律强制重写。

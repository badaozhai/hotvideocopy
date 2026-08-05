# hotvideocopy — 爆款短视频解构与复刻

## 项目目标

输入抖音 URL，自动下载并**解构**出结构化的内容 DNA（旁白/对白/人物/动作/节奏），
再基于自有题材与素材**复刻或改编**，生成新的成片。

## 核心设计原则

> **不做固化 pipeline，做 MCP 工具箱 + agent 实时编排。**

1. **工具只做确定性的事** —— 下载、切镜、抽帧、OCR、转写、调生成 API、ffmpeg 装配。
   工具**不做判断**：`scene_split` 只给切点，不判断"这是钩子"。
2. **判断和创意留给 agent** —— 在 Claude Code 里，Claude 本身就是视觉模型和文字模型。
   帧以 `ImageContent` 返回，Claude 直接看，**不要再套一层 VLM API**。
3. **状态全在文件系统** —— `dna.json` 是普通文件，用内置 Read/Edit 改，
   **不要为它写 MCP 工具**。任何一步中断可续，人可随时手改。
4. **不包简单命令** —— 转码、裁剪、抽音轨这类，Claude Code 直接 Bash。
   只包参数复杂易错的（如最终装配）。

---

## 工作区结构

```
workspace/<project_id>/
├── source.mp4          # douyin_fetch 产出
├── meta.json           # 时长/分辨率/帧率/作者/点赞等
├── shots.json          # scene_split 产出（机器写）
├── transcript.json     # transcribe 产出，带时间戳 + speaker
├── ocr.json            # 硬字幕/花字
├── dna.json            # ★ 核心资产，Claude 写/改
├── script.json         # 改写后的新剧本
├── frames/             # 抽帧缓存
├── gen/
│   ├── images/         # gpt-image-2 产出的分镜首帧
│   └── clips/          # grok 产出的视频片段
├── timeline.json       # 装配指令，Claude 写，assemble 消费
└── output.mp4
```

---

## Video DNA Schema

```jsonc
{
  "meta": { "duration": 47.2, "aspect": "9:16", "fps": 30, "bpm": 128 },
  "hook": { "t": [0, 3.0], "type": "反常识断言", "text": "..." },
  "structure": ["钩子", "冲突建立", "递进举例", "反转", "CTA"],
  "characters": [
    { "id": "A", "desc": "20代女性/职场装", "voice_spk": "SPEAKER_00" }
  ],
  "shots": [
    {
      "idx": 0,
      "t": [0, 2.1],
      "scene": "办公室工位",
      "camera": "中景/固定",
      "characters": ["A"],
      "action": "A 猛地合上笔记本站起",
      "dialogue": { "spk": "A", "text": "...", "emotion": "愤怒" },
      "narration": null,
      "on_screen_text": "第3天，我提了离职",
      "bgm_cue": "鼓点进入",
      "needs_extend": false        // duration > 15s 时标记
    }
  ],
  "rhythm": {
    "shot_durations": [2.1, 1.4, 0.8],
    "cut_on_beat": true,
    "front_load": "前3秒切4刀"
  }
}
```

**`structure` + `rhythm` 是可复用的爆款模板，`shots` 里的内容才是可替换的皮。**
改写时：抽象成骨架（去题材，只留叙事功能与时长曲线）→ 换皮 → 约束镜头数、
每镜时长、字数密度必须对齐原片。

---

## MCP Server 工具清单

单一 server，FastMCP (Python) + stdio。跨 server 传路径很痛苦，不要拆。

| 工具 | 说明 |
|---|---|
| `douyin_fetch(url)` | 下载无水印 + meta，落盘到工作区 |
| `video_import(path)` | 本地视频（录屏/相册导出）导入当源片，产出与 douyin_fetch 对齐 |
| `scene_split(video, threshold=27)` | PySceneDetect ContentDetector，产出 shots.json |
| `get_frames(video, timestamps[])` | **返回 ImageContent**，Claude 直接看 |
| `transcribe(video)` | 分离人声后转写，带时间戳；说话人分离用 pyannote |
| `ocr_burned_text(video, shots[])` | RapidOCR/PaddleOCR，抓硬字幕与花字 |
| `gen_image(prompt, refs[], size)` | gpt-image-2 |
| `gen_video_start(...)` → `gen_video_get(id)` | grok，**必须异步分离** |
| `tts(text, voice)` | 见"音色"一节 |
| `assemble(timeline_json)` | ffmpeg 精确裁切 + 拼接 + 铺音 |

### get_frames 是关键

```python
@mcp.tool()
def get_frames(video: str, timestamps: list[float]) -> list[ImageContent]:
    """抽取指定时间点的帧，直接返回图像供查看"""
    return [ImageContent(type="image", data=b64, mimeType="image/jpeg")
            for b64 in _extract(video, timestamps)]
```

一次调用 Claude 就看到画面，无需再调外部 VLM。

---

## 模型分工

| 环节 | 模型 | 备注 |
|---|---|---|
| 画面理解 / DNA 缝合 / 剧本改写 | **Claude Code 里的 Claude** | 默认路径 |
| 无人值守批处理时的理解/结构化 | `gpt-5.6-luna` | nano 档，1.05M context，适合高吞吐可校验的活 |
| 无人值守时的剧本改写 | `gpt-5.6-sol` | ⚠️ 别用 Luna 省这个钱，这是质量瓶颈且 token 量极小 |
| 分镜首帧 / 角色定妆图 | `gpt-image-2` | 多参考图组合，文字渲染强（适合花字卡） |
| 视频生成 | `grok-imagine-video-1.5` | 见下方约束 |

⚠️ `gpt-5.6` 这个 alias 路由到 Sol 而非 Luna，要 Luna 必须显式写 `gpt-5.6-luna`。

---

## Grok Imagine 约束（务必遵守）

端点：`POST https://api.x.ai/v1/videos/generations` → `request_id` → 轮询 `GET /v1/videos/{id}`
状态：`pending` / `done` / `expired` / `failed`

| 项 | 约束 |
|---|---|
| `duration` | **1–15 秒**，整数 |
| `aspect_ratio` | `9:16`（本项目固定） |
| `resolution` | 1080p 仅 T2V / I2V；**reference-to-video 封顶 720p** |
| 模式互斥 | `image` 与 `reference_images` **不能同传**，否则 400 |
| 视频编辑 | 不支持自定义 duration/aspect/resolution，原时长上限 8.7s |
| 超 15s 长镜 | 用 Video Extension（`/v1/videos/extensions`）从末帧续接 |
| 输出 URL | **临时链接**，`gen_video_get` 内部必须立即下载落盘 |
| 并发 | SDK 有 `AsyncClient`，分镜批量用 `asyncio.gather` |

### 音色：不能靠 Grok

`reference_audios` 只接受**内置预设 `voice_id`**，无法上传自己的音频；单次最多 3 个，
prompt 里用 `<AUDIO_0>` / `<AUDIO_1>` / `<AUDIO_2>` 索引。且该能力目前仅在美国对
可信合作伙伴开放。

**因此：生成视频时把 Grok 自带音轨整条丢弃，人声与 BGM 全部后期铺。**
TTS 走 IndexTTS-2 / CosyVoice 2（本地，可音色克隆），或 xAI TTS + Custom Voices。

### 角色一致性策略

两条路二选一（模式互斥）：

- **推荐** — gpt-image-2 先出角色定妆图，再为每个 shot 出首帧（带定妆图作参考），
  然后走 `image` 模式 I2V → 可拿 1080p，可控性更强
- 备选 — 定妆图直接作 `reference_images` 走 reference-to-video → 封顶 720p

### 时长对齐

`duration` 只能整数秒，原片镜头常是 2.37s 这种小数。
**生成时向上取整，装配时用 ffmpeg 精确裁到 DNA 时间轴** —— 节奏才对得上原片。

---

## 开发路线

**第一阶段：只做解构链路**（先跑通，别急着往下推）

- [x] `douyin_fetch`（另有 `video_import` 收本地录屏/任意视频，源不限于抖音）
- [x] `scene_split`
- [x] `get_frames`
- [x] `transcribe`
- [ ] 手工验证：能产出人类可读的分镜表

DNA 的质量决定后面一切。这一步做扎实，它本身就是个能用的工具。

**第二阶段：OCR + DNA 稳定**

- [x] `ocr_burned_text`（别省，抖音花字只有 OCR 拿得到）
- [ ] DNA schema 固化，跑 10 条以上样本验证稳定性

**第三阶段：生成端**

- [ ] `gen_image` → 定妆图 + 分镜首帧
- [ ] `gen_video_start` / `gen_video_get`
- [ ] `tts`
- [ ] `assemble`

---

## 技术依赖

```
yt-dlp              # 抖音下载，注意 cookie 与风控
PySceneDetect       # 镜头分割
ffmpeg / ffmpeg-python
demucs              # 人声/BGM 分离，显著提升 ASR 准确率
faster-whisper      # 或 xAI Speech to Text
pyannote.audio      # 说话人分离
rapidocr-onnxruntime # 硬字幕 OCR
librosa             # BPM / onset，卡点对齐
mcp                 # FastMCP
openai              # gpt-image-2 / gpt-5.6-*
xai-sdk             # grok-imagine-video-1.5
```

LLM 调用统一走自建 CLIProxyAPI 网关；xAI 兼容 OpenAI 协议
（`base_url="https://api.x.ai/v1"`）。

---

## 合规边界

复刻的合法边界在**结构与创意方法**，不在具体表达。台词、画面、BGM 直接照搬会踩
版权和平台去重。**在 pipeline 里硬性约束：DNA 只保留结构与节奏，具体内容强制重写。**

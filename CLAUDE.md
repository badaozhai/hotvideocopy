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
├── storyboard.json     # ★ 源片分镜工程文件，时间轴对齐的唯一真值
├── dna.json            # ★ 核心资产，Claude 写/改
├── script.json         # 改写后的新剧本
├── frames/             # 抽帧缓存
├── gen/
│   ├── images/         # gpt-image-2 产出的分镜首帧
│   └── clips/          # grok 产出的视频片段
├── references/         # 角色身份板、定妆图和场景参考
├── motion/             # 姿态轨、控制片和动作 QA
├── motion_segments/    # 按镜头或段落切出的姿态控制视频
├── timeline.json       # 装配指令，Claude 写，assemble 消费
├── production.json     # 目标成片的选片、返工、QC、交付档案
├── production.md       # 创意项目的剧本、定妆与镜头约束
├── qc/                  # 拼墙、探针和人工验收产物
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

### 音频策略（2026-08 实测更新，推翻旧结论）

**Grok 能演中文对白。** prompt 里写 `says in Chinese: "台词"`，生成带口型同步的中文语音，
实测 whisper 回验一字不差。**对白镜头的原声必须保留**，这是成片"像戏"的关键。

**Grok 片段全部自带环境音**（雨声/街噪/门厅混响），也别丢——环境音分级铺回：

| 镜头类型 | 音频处理 |
|---|---|
| 对白戏 / 动作戏 | 原声全音量（timeline.audio 引用片段本身，trim 对齐画面） |
| 过场镜（有旁白压着） | 原声 -8 ~ -10dB 垫底 |
| 卡片/彩条 | 无 |

仍然不行的：音色克隆（`reference_audios` 只收内置 voice_id 且仅美国可信伙伴可用）。
**旁白/内心 OS 用 TTS**（edge-tts 兜底已内置；音色克隆需求出现再上 IndexTTS-2/CosyVoice 2）。

---

## 导演规范（成片验收标准，写 script.json 前必读）

样板反面教材：全旁白+无声画面 = "动画版幻灯片"，用户明确拒绝。

1. **对白戏优先**：关键情感节点（钩子/冲突/和解）必须是角色开口演的对白戏，
   不许用旁白转述。旁白只做内心 OS 与过场，**句数 ≤ 镜头数的一半**。
2. **动作链三段式**：事件必须拍全"铺垫 → 瞬间 → 后果"（如：骑行→摔车→捡餐盒），
   不许跳过关键动作帧拿旁白糊弄。
3. **表演拍分解（micro-beats，最容易漏的一层）**：每个叙事 beat 拆成表演拍——
   动机 → 行动 → 犹豫/障碍 → 对方反应 → 结果，一拍一镜（2-4s）。
   写 script 前先出**表演分解表**（每拍：角色/情绪/动作），再映射成镜头。
   硬性规则：情感 payoff 前必须有铺垫镜（急着小跑去、抬手又不敢按门铃的忐忑）；
   重要动作必须配**对方的反应镜**（门内闻铃快步来开、开门瞬间惊讶的特写）。
   一个镜头囫囵吞掉整段前因后果 = 返工。
4. **连贯性走查（装配前）**：沿因果链过一遍 script——每个 payoff 找得到铺垫镜？
   每个动作找得到反应镜？每个角色的情绪曲线无跳变？缺哪拍补哪拍。
5. **道具真实**：手机聊天/App 界面/票据类道具用 PIL 像素级合成（状态栏/头像/气泡/输入栏，
   头像从定妆图裁脸），不要 AI 直出的"示意图感"气泡卡。
6. **QC 环强制**：对白片段生成后必须 `transcribe` 回验台词逐字正确；每镜抽帧拼墙
   人工过目；不合格单镜重生成，不许带病装配。
7. **响度**：assemble 的 loudnorm 默认开（-14 LUFS），别关。
8. **时长预算**：先 TTS 后排轴——旁白实际时长必须 ≤ 所在镜头时长，超了改词或换镜头长度。

### 角色一致性策略

两条路二选一（模式互斥）：

- **推荐** — gpt-image-2 先出角色定妆图，再为每个 shot 出首帧（带定妆图作参考），
  然后走 `image` 模式 I2V → 可拿 1080p，可控性更强
- 备选 — 定妆图直接作 `reference_images` 走 reference-to-video → 封顶 720p

### 时长对齐

`duration` 只能整数秒，原片镜头常是 2.37s 这种小数。
**生成时向上取整，装配时用 ffmpeg 精确裁到 DNA 时间轴** —— 节奏才对得上原片。

---

## 已落地的视频制作链路（2026-08）

### 舞蹈复刻：姿态驱动 + 外部编辑 + 本地装配

`docs/dance_video_pipeline.md` 是当前可复用的操作说明。核心脚本如下：

| 环节 | 脚本 | 结果 |
|---|---|---|
| 双角色动作提取 | `scripts/dance_pose_extract.py` | 478 帧角色锁定动作轨和控制视频 |
| 角色身份参考 | `scripts/dance_identity_boards.py` | 孙悟空、嫦娥的身份板 |
| 外部视频编辑 | `scripts/dance_external_edit.py` | 三段控制片提交、轮询和下载 |
| 成片装配 | `scripts/dance_assemble.py` | 30fps、1254x720、478 帧、原 BGM 回铺 |
| 最终质检 | `scripts/dance_final_qc.py` | 帧数、规格、OCR、控制色和音频一致性 |

该链路的输入、控制片、角色图和输出全部只留在 `workspace/`，不提交 Git。视频接口的状态查询可能以 HTTP 202 返回生成进度，`hotvideocopy.video.get()` 已兼容该响应。

### 本地模型策略

本地 SD1.5 姿态重绘只用于试验或补救。`scripts/dance_local_models.py` 提供 `--dry-run` 和按需下载；成功下载并验证可用的模型与运行环境默认长期保留，后续直接复用，不得在交付后自动删除。只有用户再次明确要求释放空间时才可清理。`dance_local_repaint.py`、`dance_local_face_refine.py` 和 `dance_local_face_swap.py` 是单帧质量验证工具，不应被当作整片默认生产路线。

语音、配乐和口型模型统一由 `scripts/local_media_models.py` 按需管理，全部放在 `workspace/.local_ai/`。下载时先做无代理直连测速；直连失败或低于快速阈值时，再比较 `.env` 已配置代理和本机 `http://127.0.0.1:8080`，自动使用实测最快的可用线路。Hugging Face 权重沿用同一缓存并支持换线路断点续传。已经成功下载的模型和隔离运行环境必须永久保留，重复安装直接复用缓存且不得联网；除非用户再次明确要求清理并提供显式确认，否则所有 `purge` 调用都必须拒绝。配音、配乐、口型、安装和显式清理共用跨进程独占队列，任何时刻只加载一个大模型，任务结束只释放内存。只可自动删除确认损坏或重复的临时下载。下载或推理期间可用空间一旦低于 1 GiB 必须立即停止任务，不能通过自动删除已安装模型来腾空间。能力边界和官方资料记录在 `docs/local_media_models.md`。

### 图像服务

图片生成优先经项目的 `hotvideocopy.images.generate()` 调用已配置网关，产物落在 `workspace/<project_id>/gen/images/`。运行时从 `.env` 读取网关地址、Key、代理和模型选择；不得输出、复制或提交任何凭据。图像接口串行排队，避免上游并发导致 502。

### 当前创作项目：虚构农村恐龙养殖采访

工作区为 `workspace/dinosaur_farm_interview/`，制作档案为 `production.md`。这是明确虚构的新闻纪实风短片：第一人称记者手持拍摄、轻微自然抖动、真实农村材质与自然光、快速多镜头切换。禁止媒体台标、字幕、水印、可读招牌、卡通恐龙、主题公园和科幻实验室画风。先锁定人物、场景和动物定妆，再使用它们生成分镜首帧与视频。

### 成片交付与发布文案

每条成片在通过画面、时长、音轨与无文字污染 QC 后，必须一并交付四组简短发布文案：抖音、小红书、朋友圈与 X（Twitter）。每组包含可直接发布的正文和平台适用关键词/标签；文案与成片一同保存到 `workspace/<project_id>/`，不提交 Git。

- 真实题材不得夸大、编造事实；虚构纪实、新闻采访风或 AI 设定必须在文案中清楚标注“虚构”或等效表述，不能伪装成真实报道。
- 避免捏造人物姓名、机构、地名、真实媒体背书、数据或成果；使用通用角色称呼，除非用户已提供可用名称。
- 文案保持简短、有明确观看引导；不在成片中强加字幕或水印来替代文案。
- 根据平台语境调整：抖音突出钩子与节奏，小红书突出创作背景与观感，朋友圈自然克制，X 同时提供简明英文版本和英文标签。

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

- [x] `gen_image` → 定妆图 + 分镜首帧
- [x] `gen_video_start` / `gen_video_get`（另有 extend / jobs）
- [x] `tts`（网关 /v1/audio/speech；本地音色克隆引擎待需求）
- [x] `assemble`（精确裁切 + 统一规格拼接 + 铺音 + 烧字幕，真片验证过）

**第四阶段：端到端创作实验**（已做五部成片,结论:读懂未扎实前创作是空中楼阁——转向）

**★ 现行主线(2026-08 重定):读懂 → 1:1 复刻 → 封版 → 创作=复刻微调**

- [x] **读懂基础设施**:storyboard_build.py 已能汇总 shots/motion/ASR/OCR/逐镜描述，
      storyboard_lint.py 已提供基础与严格校验，storyboard_report.py 已落盘确定性 QA 指标；
      三个代表项目已有初版 storyboard.json 与 qc 报告
- [ ] **读懂验收**:分镜工程文件 storyboard.json(时间轴对齐分层 schema,见
      skill references/storyboard-schema.md)通过冷读 QA + 弱还原双验证
- [ ] **1:1 复刻**:同镜头数/同台词量/同节奏,人物素材替换,逐 shot 生成,达标封版
- [ ] **创作**:复刻基础上微调,不另起炉灶

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

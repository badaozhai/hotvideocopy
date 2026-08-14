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

### 本地视频模型（按需下载）

本机姿态重绘路线不是 Grok 流程的必需依赖。需要恢复本机生成时，先配置可用的 `HVC_HF_TOKEN`（或 `HF_TOKEN`）和可选的 `HVC_PROXY`，再执行：

```bash
.venv/bin/python scripts/dance_local_models.py --dry-run
.venv/bin/python scripts/dance_local_models.py
```

脚本会下载 DreamShaper 8、DreamShaper 8 LCM、OpenPose ControlNet、IP-Adapter Plus SD1.5、InsightFace `buffalo_l` 和 `inswapper_128`，并把校验清单写到 `workspace/dy_7671559890300685604/local_models_manifest.json`。默认不保留 InsightFace 压缩包；完整安装约需 8.5 GiB 临时空间，安装后约 8.2 GiB。下载方法保存在 [scripts/dance_local_models.py](scripts/dance_local_models.py)。

### 本地语音、配乐与口型模型

本地媒体模型统一保存在 `workspace/.local_ai/`，使用隔离运行环境。单次任务结束只释放内存，模型文件和运行环境永久保留；重复安装会直接复用完整缓存，不测速、不联网、不重装。配音、配乐、口型、安装和显式清理共用跨进程队列，任何时刻只加载一个大模型。安装与推理过程都会保留至少 1 GiB 可用磁盘空间。

```bash
.venv/bin/python scripts/local_media_models.py status
.venv/bin/python scripts/local_media_models.py estimate voice --variant custom
.venv/bin/python scripts/local_media_models.py install voice --variant custom
.venv/bin/python scripts/local_media_models.py install music
.venv/bin/python scripts/local_media_models.py install lipsync --variant mlx
```

下载会先测试直连；直连过慢时再比较 `.env` 配置的代理与 `http://127.0.0.1:8080`，使用实测最快的可用线路，并保留可续传的 Hugging Face 缓存。

清理命令默认拒绝删除。只有用户再次明确要求清理时，调用方才可额外传 `--confirm-explicit-user-request`。模型选择依据、已验证能力和真实边界见 [docs/local_media_models.md](docs/local_media_models.md)。

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
| `video_import(path)` | 解构 | 导入本地 MP4/MOV，产出与 `douyin_fetch` 对齐的工作区 |
| `scene_split(video)` | 解构 | PySceneDetect 切镜（退路 ffmpeg），产出 `shots.json` + 时长曲线 |
| `get_frames(video, ts[])` | 解构 | 返回 `ImageContent`，Claude 直接看画面 |
| `video_info(video)` | 解构 | 时长/分辨率/帧率/编码/音轨 |
| `transcribe(video)` | 解构 | 人声分离、ASR 时间戳，按环境安装情况提供说话人信息 |
| `ocr_burned_text(video)` | 解构 | OCR 抓硬字幕、标题花字和贴纸时间段 |
| `gen_image(...)` | 生成 | gpt-image-2，无 refs=定妆图，有 refs=锁脸出首帧 |
| `gen_video_start(...)` | 生成 | grok，**发起即返回 request_id，不阻塞** |
| `gen_video_get(id)` | 生成 | 查状态，done 当场落盘（上游是临时链接） |
| `gen_video_extend(...)` | 生成 | 从末帧续接，超 15s 长镜用 |
| `tts(text, voice)` | 生成 | 已安装时优先本地 Qwen3-TTS；支持情感指令、北京话、四川话与授权音色克隆 |
| `local_music_generate(...)` | 生成 | 本地 ACE-Step Turbo 歌曲/配乐，支持歌词结构、BPM、调式、拍号和风格提示 |
| `local_lipsync(...)` | 后期 | 本地 LatentSync MLX 单人逐镜口型同步 |
| `assemble(timeline)` | 装配 | 精确裁切、统一规格、铺音、可选字幕 |
| `gen_video_jobs()` | 运维 | 任务清单打捞——会话断了片不会变孤儿 |
| `workspace_info()` | 运维 | 配置与工作区状态自检 |

## 配音工作台

项目内置一个本地单页面配音工作台。它使用 Apple Silicon 优化的 Qwen3-TTS
1.7B 8-bit 模型；生成文件落在 `workspace/<project_id>/gen/local_voice/`，可直接交给
`timeline.json` 装配。模型只在生成子进程中载入，任务结束释放内存，权重和运行环境永久保留。

```bash
.venv/bin/hotvideocopy-web
```

启动后会自动打开 `http://127.0.0.1:8765/`。也可以用 `--no-open` 只启动服务，
或用 `--port 8766` 换端口。

页面支持：

- Qwen3-TTS CustomVoice 预设音色、普通话/北京话/四川话及自然语言表演指令
- Qwen3-TTS Base 约 3 秒参考音频克隆；必须提供逐字稿并确认已获得音色授权
- 0.75–1.35 倍后期无损时长调节，试听、下载和最近导出记录
- 配置了 `HVC_BASE_URL` 与 `HVC_API_KEY` 时，用 AI 网关润色台词；没有配置时退回本地断句
- 页面仅提供安装入口；安装成功后显示“已安装 · 永久保留”，不会自动清理模型

## 本地歌曲与配乐

ACE-Step 1.5 Turbo 支持无歌词配乐、带歌词歌曲、BPM、调式、拍号，以及提示词里的乐器和演唱风格。歌词可直接写 `[Verse]`、`[Chorus]`、`[Bridge]` 标签，也可给 `local_music_generate` 传 `structure="ABBA"` 和 `sections` 自动展开 AABA、ABBA、BAB 等段落。当前 Turbo 只开放已经验证的 `text2music`、`cover`、`repaint`；分轨、Lego 和补全属于未安装的 Base 版，不会误报为当前能力。

**没有** dna.json 的读写工具：那是普通文件，用内置 Read/Edit 改。
**没有** 转码/裁剪工具：直接 Bash ffmpeg。

## 桌面 GUI「写轮眼」

`gui/` 是 Tauri v2 桌面 App(品牌名写轮眼),作为整个工具箱的统一壳:

- **项目**:工作区查看器——分镜墙(缩略图+台词/花字对齐时间轴)、生成素材画廊、
  工程 JSON、源片/成片播放。抽帧与 MCP 侧共用 `frames/` 缓存。
- **配音**:一键拉起并托管 `hotvideocopy-web` 子进程(退出随 App 回收,不留孤儿),
  子窗口打开配音工作台,能力与浏览器版完全一致。
- **模型**:本地模型管理原生页——硬件/磁盘/`.local_ai` 占用、六套运行环境状态、
  七个模型卡(Qwen3-TTS 双版/CosyVoice3/IndexTTS/ACE-Step/LatentSync/MuseTalk)
  的安装与任务进度轮询。遵循上游策略:只装不删,清理走命令行显式确认。
- **新任务**:选流水线(端到端复刻 / 1:1 复刻 / 仅解构 / 本地配乐 / 口型同步)
  生成标准指令,复制贴进 Cursor / Claude Code 执行——流水线由 agent 编排,GUI 不假装能跑。
- **设置**:端点/Key(带连通性测试)与模型选择,写仓库根 `.env`,与 MCP server 同源配置。

```bash
cp "$(which ffmpeg)" gui/src-tauri/binaries/ffmpeg-aarch64-apple-darwin   # sidecar 按平台命名
cd gui/src-tauri && cargo build        # 开发版;发行版用 npx @tauri-apps/cli build
```

另有不打包的轻量版 `hotvideocopy-ui`(Python + 浏览器,只读查看器)。

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

### 分镜工程文件

`storyboard.json` 是源片的时间轴真值，`production.json` 是目标成片的制作档案。
已有项目可以用以下命令做基础或严格校验：

```bash
.venv/bin/python scripts/storyboard_lint.py <project_id>
.venv/bin/python scripts/storyboard_lint.py <project_id> --strict
.venv/bin/python scripts/storyboard_report.py <project_id> --strict
.venv/bin/python scripts/keyframes_from_storyboard.py <project_id> --dry-run
```

`storyboard_build.py` 兼容正式 MCP 的 `t: [start, end]` 和历史复刻脚本的
`t_start/t_end` 两种镜头格式；它只合并确定性数据，场景、人物和动作描述仍由 agent 回填。
因此，机器汇总完成后先跑基础校验；逐镜描述回填完成，再跑 `--strict` 作为读懂验收门禁。
`storyboard_report.py` 会把确定性指标写入 `qc/storyboard_report.json/md`，并明确标出仍需人工完成的冷读 QA 与弱还原。
`keyframes_from_storyboard.py --dry-run` 只生成关键帧计划，不调用图片 API；角色参考图优先读取
`global.characters[].asset`，缺失时才回退到 `repl_P1/repl_P2` 占位路径。

## 状态

- [x] 骨架 + `douyin_fetch` / `scene_split` / `get_frames`
- [x] gpt-image / grok 能力移植（自 `henduohao`）
- [x] `video_import` / `transcribe` / `ocr_burned_text`
- [x] `tts` / `assemble`
- [x] `gen_video_extend` / `gen_video_jobs` / `workspace_info`
- [x] `storyboard_build.py`：分镜工程文件汇总
- [x] `storyboard_lint.py`：基础结构校验 + 严格语义校验
- [x] `storyboard_report.py`：确定性 QA 指标与人工门禁报告
- [x] `keyframes_from_storyboard.py --dry-run`：弱还原任务计划
- [ ] 冷读 QA 与弱还原的人工验收闭环
- [ ] r5-r8 复刻脚本提炼为 action / dialogue / pov / quote 模板

## 合规

复刻的合法边界在**结构与创意方法**，不在具体表达。DNA 只保留结构与节奏，
台词、画面、BGM 一律强制重写。

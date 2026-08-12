# 本地语音、配乐与口型模型

更新时间：2026-08-12。本文只记录本机已验证能力；上游宣称但本机未安装、未运行的能力不会标为可用。

## 当前选择

| 环节 | 本机模型 | 已验证能力 | 许可 | 本机适配 |
|---|---|---|---|---|
| 角色配音 | Qwen3-TTS CustomVoice 1.7B 8-bit MLX | 中文、多语言、自然语言情感/语气指令、9 个预设音色；Dylan 为北京话，Eric 为四川话 | Apache-2.0 | 约 3-5 GiB 统一内存，逐句子进程运行 |
| 授权音色克隆 | Qwen3-TTS Base 1.7B 8-bit MLX | 参考音频音色克隆、跨语言合成；工作台强制逐字稿和授权确认 | Apache-2.0 | 约 3-5 GiB 统一内存，逐句子进程运行 |
| 歌曲与配乐 | ACE-Step 1.5 Turbo MLX | 文生音乐、歌词、段落标签、BPM、调式、拍号、提示词乐器/风格、参考音频翻唱和重绘 | MIT | 本机临时服务，任务结束终止 |
| 口型同步 | LatentSync 1.5 MLX | 中文音频、单人逐镜口型、256px 人脸区域、身份保持 | Apache-2.0 | 约 8 GiB 统一内存起，逐镜子进程运行 |

Qwen3-TTS 当前模型配置只直接列出北京话和四川话。CosyVoice 3 的上游资料提供更广的中国方言覆盖，但本机没有安装或接入该模型，因此不能把“18+ 方言”算作当前能力。IndexTTS 2.5 同样仅保留调研项，官方运行路径以 CUDA 为主，不作为这台 Apple Silicon 机器的默认方案。

ACE-Step 当前安装的是 `acestep-v15-turbo`、VAE 和 Qwen3 Embedding。官方模型表中 Turbo 支持 Text2Music、Cover 和 Repaint，不支持 Base 版才有的 Extract、Lego 与 Complete；当前也没有安装可选 5Hz LM。直接给定歌词、BPM、调式和拍号不需要 LM。

因此当前工具固定使用 `thinking=false`。若误传 `thinking=true` 会直接拒绝，不会尝试联网补下载可选 LM。

## 歌曲结构

`local_music_generate` 接受两种歌词方式：

- 直接传带 `[Verse]`、`[Chorus]`、`[Bridge]` 等标签的 `lyrics`。
- 传 `structure="ABBA"` 和 `sections={"A": "主歌", "B": "副歌"}`，工具会按顺序展开成 ACE-Step 段落标签。A-F 依次映射为 Verse、Chorus、Bridge、Pre-Chorus、Instrumental Break、Outro，也支持 AABA、BAB 等结构。

歌曲和配乐还可以显式控制 `bpm`、`key_scale`、`time_signature`、`vocal_language`、时长、种子与提示词中的乐器/演唱风格。纯音乐使用 `instrumental=true`；翻唱或重绘必须提供参考音频。

## 生命周期与磁盘

- 所有模型、源码、缓存和隔离运行环境都在 `workspace/.local_ai/`。
- 配音、配乐、口型、安装和显式清理共用跨进程独占队列，任何时刻只运行一个大模型任务。
- 每个任务结束只退出子进程或临时服务以释放内存，不删除权重和运行环境。
- 已完整安装的模型再次执行安装时直接复用缓存，不测速、不联网、不重装。
- 下载时先测试直连；直连慢于阈值后，再比较 `.env` 代理与 `http://127.0.0.1:8080`。
- 下载、模型启动和推理过程中可用空间低于 1 GiB 立即停止，不能通过自动删除已安装模型腾空间。
- 清理接口默认拒绝执行。只有用户再次明确要求，且调用方传入显式确认参数，才允许删除。

## 本机证据

- 安装状态：`workspace/.local_ai/install_manifest.json`
- 16 句配音回验：`workspace/dinosaur_farm_interview/dialogue_asr_report.json`
- 5 个可见说话镜头：`workspace/dinosaur_farm_interview/lipsync_render_report.json`
- 本地配乐：`workspace/dinosaur_farm_interview/gen/music/dinosaur_documentary_bed_v2.mp3`
- 最终成片质检：`workspace/dinosaur_farm_interview/final_local_qc.json`

## 上游资料

- [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS) 与 [MLX CustomVoice 模型卡](https://huggingface.co/mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit)
- [MLX Base 模型卡](https://huggingface.co/mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit)
- [ACE-Step 1.5](https://github.com/ACE-Step/ACE-Step-1.5)
- [ByteDance LatentSync](https://github.com/bytedance/LatentSync) 与 [LatentSync MLX](https://github.com/sb1992/latentsync-mlx)
- [Fun-CosyVoice](https://github.com/FunAudioLLM/CosyVoice) 和 [IndexTTS](https://github.com/index-tts/index-tts) 仅作为未安装候选记录

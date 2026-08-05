---
name: replicate
description: 爆款短视频端到端复刻流水线：解构→DNA→换皮→生成(带QC环)→装配验收。输入抖音链接/本地视频 + 新题材,产出成片。用户说"复刻这条""换成XX题材再来一条"时用。
---

# 复刻流水线

输入：源视频（抖音链接走 `douyin_fetch`，本地文件走 `video_import`）+ 新题材方向。
产出：`workspace/<pid>/output.mp4` + dna.json / script.json / timeline.json / subs.srt。

严格按阶段走，**每个 QC 门不过就地返工，不许带病进下一阶段**。

## 一、解构（并行跑）

1. `scene_split` → 切镜；`transcribe`（后台）→ 台词；`ocr_burned_text`（后台，需 shots.json 先落盘）→ 花字/字幕/截图卡。
2. 中点帧拼墙一次看全（ffmpeg xstack），逐镜认类型：实拍长镜 / 梗卡 / 截图卡 / 空镜 / CTA。
3. 台词按镜头时间轴 join，产出人类可读分镜表。

## 二、DNA 提炼 → dna.json

只留**结构与节奏**，具体内容全部丢弃（合规红线）：
- hook 公式（冷开场金句前置/花字剧透/掐断手法）
- structure beats（叙事功能序列 + 时间占比）
- rhythm（shot_durations、疏密模式、卡点逻辑）
- formula(narrative/emotion_curve/series_glue)——抽象到与题材无关

## 三、换皮 → script.json（导演规范，见 CLAUDE.md）

**先读 `references/film-language.md`（镜头语言与表演设计手册），再出表演分解表
（beat sheet），最后写分镜**——这是质量的分水岭：

1. 每个叙事 beat 按手册"时序模板"拆表演拍：铺垫→障碍→行动→反应→悬念→payoff→余韵，
   每拍标（角色 / 情绪 / 外化动作(查词典①) / 景别 / 运镜），一拍一镜 2-4s
2. 硬性检查（QC 口诀）：**铺垫拍、障碍拍、反应拍、余韵拍——四拍缺一即返工**；
   情绪节点必须有特写；情绪转变必须分拍（愣住→捂嘴→笑，一步到位就假）
3. 表演拍确认完整后才映射成 shots，I2V prompt 按手册"组装公式"写

镜头类型分配：
- **对白戏**：钩子/冲突/和解等情感节点，角色开口演。每镜标 `kind: dialogue` 并写台词
- **动作戏**：事件三段式"铺垫→瞬间→后果"，一段都不能省
- **过场镜**：可配内心 OS 旁白。**旁白总句数 ≤ 镜头数一半**
- **道具卡**：聊天界面/票据用 PIL 像素合成（状态栏+定妆图裁脸头像+气泡+输入栏），
  时间卡/CTA 卡可 gpt-image-2 直出（中文渲染可靠）
- 节奏对齐 DNA：疏密比例、front_load、卡点位置照搬骨架

## 四、生成（串行图 → 并行视频 → QC）

1. 定妆图（每角色一张，3/4 身位纯色背景）→ 人工看图过目
2. 首帧：带定妆图 refs 走 I2I 锁脸；出图后 `crop` 到 9:16（gpt-image 是 2:3）
3. I2V 全部发起（`gen_video_start`，duration 向上取整）：
   - 对白镜 prompt 写 `says in Chinese: "台词"`，结尾加 lip sync 要求
   - 动作镜写清动作全程；所有镜加 `cinematic realistic`
4. TTS 旁白逐句出（`tts`），**记录每句 duration**——超镜头预算就改词
5. **QC 门**：
   - 对白片段 `transcribe` 回验，台词必须逐字正确，错了改 prompt 重生成该镜
   - 全部片段抽帧拼墙过目：人物一致性/动作完成度/穿帮
   - 失败重试免费重发；「上游终止」多为内容审核，软化措辞重发

## 五、装配前：连贯性走查

沿因果链把 script 过一遍：每个 payoff 找得到铺垫镜、每个动作找得到反应镜、
每个角色情绪无跳变。缺拍 → 回第四阶段补生成，**不许带病装配**。

## 六、装配 → timeline.json → `assemble`

- video[]: trim 精确裁回 DNA 时间轴
- audio[] 分级：对白/动作镜引用片段自身原声（全量）；过场镜原声 -8~-10dB 垫底；
  旁白 mp3 按 TTS 实测时长排 `at` 落点（可跨切声画桥接）
- `loudnorm: true`（默认，别关）；字幕**不烧**，subs.srt（对白+旁白）交后期
- 验收：duration 与排轴一致（±0.2s）、volumedetect 峰值 > -3dB、抽 4-6 帧终检

## 已知坑（都踩过）

- gpt-image 并发必须 1（502）；grok 结果 URL 可能是相对路径（代码已处理）
- 中转无 audio/speech 路由 → tts 自动落 edge-tts
- zsh 无词切分：Bash 循环里别用 `set -- $var`
- ffmpeg `apad,atrim` 死锁（assemble 已修，别在别处复刻这个写法）
- 同项目转写生成片段：asr 缓存已按文件分键，放心用

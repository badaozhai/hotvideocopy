# 按镜复刻管线脚本归档(2026-08 实战版)

三轮实战验证的完整链路,路径含会话 scratchpad 硬编码,复用时先改 SP/PID:

- **r2_***: 精武门 46 镜(武打,I2V 死角实证)——extract(切shot/采样/光流) → redraw(定妆参考+三层防护) → gen(双备选+身份人数锁) → assemble(剪辑点+KB兜底)
- **r3_***: 夜市段子 13 镜(甜区验证 13/13 零重做)——r3_assemble_v2 含竖版主体感知裁切 + TTS 配音 + demucs 伴奏 + 电话滤波
- **r4_***: 悟空八戒换皮版(创作=复刻微调)——含台词逐字锁、口型锁(非对白镜闭嘴)、
  台词锚定画面事件、grok 对白原声混音

配套规范见 .claude/skills/replicate/references/film-language.md 第十三章(选型门禁/死角图谱/音画对位三律)。

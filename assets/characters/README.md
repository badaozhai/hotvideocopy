# 角色定妆资产(固定资产,勿随 workspace 清理)

用户确认封版的定妆图(2026-08-08 审定,悟空八戒版成片 final_wukong.mp4 全程使用)。
换皮创作时作为 gpt-image-2 的 refs 使用;**图 + 下方文字锁是一套资产,必须配套使用**——
prompt 里的外观描述与定妆图不一致时,I2V 会向文字侧漂移。

## 孙悟空 — `wukong.png`

文字锁(逐字复制进首帧与 I2V prompt):

> 孙悟空(金棕猴脸,金紧箍,鹅黄僧衣+虎皮围裙,黑腕表,红色手机)

## 猪八戒 — `bajie.png`

文字锁:

> 猪八戒(粉灰猪头,大耳长吻,藏青僧衣敞怀露肚,大念珠)

## 使用要点(实案沉淀,详见 .claude/skills/replicate/references/film-language.md 13.5-13.7)

- 首帧生成:refs = [原片构图参考图, 本定妆图],并声明"定妆图仅定义人物外观,
  其画面内容/背景/构图一律不得带入结果"
- CG 角色会**向人类漂移**(猴脸人化/猪头人化),每镜 QC 必查身份
- 风格咒语:角色是电影级 CG 特效神话人物,与实拍夜市环境自然融合
  (photorealistic live-action + movie-grade CG creatures composited)
- 版权口径:《西游记》为公版古典名著,角色为原创设计(FRAMING 语句见 r4_redraw.py)

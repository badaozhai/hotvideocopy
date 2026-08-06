# 分镜工程文件 storyboard.json —— 复刻的唯一真值

> 可还原性 = 描述的结构化程度 × 粒度,不是文笔。
> 还原"信息"而不是"像素":台词/镜头结构/动作节奏/字幕无损;像素级细节只留风格描述。

## Schema(分层:全局 → 镜头 → 镜头内元素)

```jsonc
{
  "meta": { "source": "dy_xxx", "duration": 34.2, "resolution": "1080x1920", "fps": 30,
            "bgm": "描述或指纹(节奏/情绪/切入点)" },
  "global": {
    "genre": "剧情反转", "tone": "悬疑→搞笑",
    "characters": [
      { "id": "P1", "look": "20多岁女性,黑长直,白衬衫", "voice": "音色描述", "role": "叙事功能" }
    ]
  },
  "shots": [
    {
      "idx": 0,
      "t": [0.0, 2.8],
      "camera": { "size": "中景", "move": "手持轻晃,缓慢推近", "move_cv": "static|pan_l|pan_r|tilt|handheld|unknown", "angle": "平视" },
      "scene": "室内办公室,冷白光,背景绿植和工位",
      "subjects": [
        { "ref": "P1", "pos": "画面中央偏左", "action": "低头看手机,眉头皱起", "expr": "疑惑" }
      ],
      "dialogue": [ { "speaker": "P1", "text": "这条消息谁发的?", "emotion": "警惕", "t": [0.5, 1.9] } ],
      "narration": null,
      "overlay_text": [ { "text": "第一天上班", "pos": "顶部居中", "style": "白字黑边", "t": [0.0, 2.8] } ],
      "sfx": ["手机震动 @0.3s"],
      "transition_out": "硬切"
    }
  ]
}
```

要点:
- **人物用 ID 引用**,跨镜头一致——这是复刻时"换素材"的替换点
- `camera.move_cv` 来自 motion.py 的光流分类(ground truth),`camera.move` 是 VLM 综合判断
- dialogue/narration 由 ASR 时间戳按 shot 切分归入;overlay_text 来自 OCR spans
- 每个字段独立可重跑:单 shot 描述坏了只重跑那一个 shot

## 提取管线

```
douyin_fetch → scene_split(shots.json)
  ├─ motion.py → 每shot运镜CV分类(motion.json)
  ├─ 每shot抽帧(首/¼/中/¾/尾5帧,高运动shot加密) → VLM逐shot按schema输出
  ├─ transcribe → 带时间戳分段 → 按shot归属+说话人判断(对白/旁白区分)
  ├─ ocr_burned_text → overlay_text(按y分层:标题花字/对白字幕/贴纸)
  └─ 音轨:demucs分离 → BGM特征描述
→ 汇总:时间轴对齐、人物表跨shot re-ID、填schema → storyboard.json
```

实操要点:
1. VLM 输入 = 帧序列 + shot 时间区间 + motion 标签,prompt 强制按 schema 字段输出;绝不整条喂
2. 运镜以 motion.py 的 CV 信号为准,VLM 只做补充判断(VLM 猜运镜不可信)
3. 人物一致性:每 shot 让 VLM 输出外观描述,汇总时按外观合并成 ID(必要时加人脸 embedding)
4. 说话人归属:ASR 时间段 × 该时段画面里"谁在张嘴"(VLM 帧描述里记录口型开合)

## 可还原验证(双重)

1. **冷读 QA**:一个没看过原片的代理只读 storyboard.json 回答内容问题,
   与看过原片的答案一致 → 信息无损
2. **弱还原**:schema → gpt-image 逐 shot 出关键帧 → 与原片帧对比构图/景别/主体位置

## 阶段规划

1. **读懂**:上述管线跑通,storyboard.json 通过双重验证 → 里程碑
2. **1:1 复刻**:同镜头数/同台词量/同节奏,人物素材替换,逐 shot 生成 → 达标即封版
3. **创作**:复刻基础上微调(换题材/换台词),不另起炉灶

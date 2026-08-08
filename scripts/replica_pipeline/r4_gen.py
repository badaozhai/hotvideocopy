#!/usr/bin/env python
"""r4(悟空八戒版)I2V:重绘首帧 + 表情弧线 prompt,≥1.5s 双备选,串行+退避,可续跑。
对话戏低烈度,shot_000(7.9s)/shot_008(5.6s)先试单条生成,QC 熔了再拆。"""
import asyncio, json, math, sys, time
from pathlib import Path

sys.path.insert(0, "/Users/suifei/works/hotvideocopy/src")
import os
os.chdir("/Users/suifei/works/hotvideocopy")
from hotvideocopy import video as V

PID = "dy_7410349447718161701"
WS = f"workspace/{PID}"
IM = f"{WS}/gen/images"
C = f"{WS}/gen/clips"
Path(C).mkdir(parents=True, exist_ok=True)
SP = "/private/tmp/claude-501/-Users-suifei-works-hotvideocopy/b362c3f4-3764-4d87-a046-feaccc127248/scratchpad"

shots = json.loads(Path(f"{WS}/seg/shots.json").read_text())["shots"]
specs = {r["id"]: r for r in json.loads(Path(f"{SP}/r3_specs.json").read_text())}
overrides = {}
op = Path(f"{WS}/seg/prompts_r4.json")
if op.is_file():
    overrides = json.loads(op.read_text())

WHO = {"M1": "孙悟空(金棕猴脸,金紧箍,鹅黄僧衣+虎皮围裙,黑腕表,红色手机)",
       "M2": "猪八戒(粉灰猪头,大耳长吻,藏青僧衣敞怀露肚,大念珠)"}
MOUTH_LOCK = {
    "shot_000": "口型铁律:接起电话贴耳后全程安静聆听,嘴巴保持闭合,严禁任何说话型开合;情绪只用眉眼变化表达",
    "shot_001": "口型铁律:猪八戒不说话,嘴巴除咀嚼食物外保持闭合,严禁说话型开合;惊讶只用瞪眼挑眉表达",
    "shot_003": "口型铁律:猪八戒不说话,嘴巴除咀嚼外保持闭合,严禁说话型开合;嫌弃只用撇嘴斜眼表达",
    "shot_006": "口型铁律:全程听电话,嘴巴保持闭合,严禁说话型开合;得意只用眯眼和嘴角上扬表达",
    "shot_008": "口型铁律:全程听电话,嘴巴保持闭合,严禁说话型开合;甜笑只用眯眼弯嘴角表达",
    "shot_009": "口型铁律:猪八戒不说话,嘴巴除咀嚼外保持闭合,严禁说话型开合",
    "shot_010": "口型铁律:听电话被骂,嘴巴闭合或短暂张嘴倒吸一口气,严禁连续说话型开合;错愕用瞪眼皱眉表达",
    "shot_012": "口型铁律:不说话,嘴角下垮抿紧的苦脸,严禁说话型开合;想哭只用眉眼和嘴角表达",
}
REMAP = "注意:运动描述里的'寸头男/深墨绿衬衫寸头男'在画面中是孙悟空,'花衬衫男/黑底白花纹衬衫男'是猪八戒,动作表情照描述执行。"
FF_CAST = {"shot_000": ["M1"], "shot_001": ["M2"], "shot_002": ["M1"], "shot_003": ["M2"],
           "shot_004": ["M1"], "shot_005": ["M2"], "shot_006": ["M1"], "shot_007": ["M2"],
           "shot_008": ["M1"], "shot_009": ["M2"], "shot_010": ["M1"], "shot_011": ["M2"],
           "shot_012": ["M1"]}
OTS = {"shot_001", "shot_003", "shot_005", "shot_007", "shot_009", "shot_011"}
STYLE = ("photorealistic live-action night market, neon bokeh, shallow depth of field; the mythical "
         "characters are movie-grade CG creatures seamlessly composited into live footage, realistic fur "
         "and skin detail, like a fantasy blockbuster")

def build_prompt(sh, sp):
    sid = sh["id"]
    parts = []
    if sid in overrides:
        parts.append(overrides[sid])
    else:
        if sp.get("camera"):
            parts.append(f"镜头:{sp['camera']}")
        if sp.get("i2v_prompt"):
            parts.append(sp["i2v_prompt"])
    cast = FF_CAST[sid]
    parts.append(f"画面中自始至终只有{len(cast)}位主体人物:" + "、".join(WHO[c] for c in cast)
                 + "。人物的服装、发型、脸必须与首帧图完全一致并保持到片段结束,严禁变装换脸")
    if sid in OTS:
        parts.append("前景一侧的虚化肩背保持虚化,不得变清晰、不得露脸")
    parts.append(REMAP)
    if sid in MOUTH_LOCK:
        parts.append(MOUTH_LOCK[sid])
    parts.append("严禁任何新人物进入画面;背景路人保持虚化不清晰")
    parts.append(STYLE)
    return "; ".join(parts)

async def submit_retry(name, img, dur, prompt):
    for bo in [0, 60, 120, 240, 480, 600, 600]:
        if bo:
            await asyncio.sleep(bo)
        try:
            await V.start(prompt, project_id=PID, image=img, duration=dur,
                          aspect="16:9", resolution="1080p", name=name)
            return True
        except Exception as e:
            print(f"RETRY {name} ({str(e)[:90]})", flush=True)
    print("GIVEUP", name, flush=True)
    return False

# I2V 单图模式输出继承输入图比例(video.py 实测注释),故先把首帧裁成精确 4:3 再喂
async def wait_one(name, timeout=1500):
    t0 = time.time()
    while time.time() - t0 < timeout:
        await asyncio.sleep(28)
        for j in V.jobs(PID):
            if j["name"] == name:
                if j.get("status") == "done":
                    return True
                if j.get("status") == "failed":
                    print("FAILED", name, str(j.get("error"))[:90], flush=True)
                    return False
                try:
                    r = await V.get(j["request_id"])
                    if r.get("status") == "done":
                        return True
                    if r.get("status") == "failed":
                        print("FAILED", name, str(r.get("error"))[:90], flush=True)
                        return False
                except Exception:
                    pass
                break
    print("TIMEOUT", name, flush=True)
    return False

async def main():
    for sh in shots:
        sid = sh["id"]
        sp = specs.get(sid)
        kf0 = Path(IM) / f"r4k_{sid}.png"
        kf = Path(IM) / f"r4k4_{sid}.png"
        if sp is None or not kf0.is_file():
            print(f"SKIP {sid}", flush=True)
            continue
        if not kf.is_file():
            import subprocess
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(kf0),
                            "-vf", "crop='min(iw,ih*4/3)':'min(ih,iw*3/4)',scale=1440:1080",
                            str(kf)], check=True)
        dur = min(15, max(2, math.ceil(sh["duration"]) + 1))
        nvar = 1  # 池子紧张期:单备选,QC 不过再个案重做
        prompt = build_prompt(sh, sp)
        for k in range(nvar):
            name = f"r4v_{sid}_v{k}"
            if Path(f"{C}/{name}.mp4").is_file():
                continue
            if not await submit_retry(name, str(kf), dur, prompt):
                continue
            if await wait_one(name):
                print("DONE", name, flush=True)
            await asyncio.sleep(10)
    print("R4-GEN-ALL-DONE", flush=True)

asyncio.run(main())

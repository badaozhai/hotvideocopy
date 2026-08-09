#!/usr/bin/env python
"""r4 口型返工:s001/s003/s008 说话状张嘴,口型锁置顶强化后重生成为 v1。"""
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
SP = "/private/tmp/claude-501/-Users-suifei-works-hotvideocopy/b362c3f4-3764-4d87-a046-feaccc127248/scratchpad"

shots = {s["id"]: s for s in json.loads(Path(f"{WS}/seg/shots.json").read_text())["shots"]}
specs = {r["id"]: r for r in json.loads(Path(f"{SP}/r3_specs.json").read_text())}
overrides = {}
op = Path(f"{WS}/seg/prompts_r4.json")
if op.is_file():
    overrides = json.loads(op.read_text())

WHO = {"M1": "孙悟空(金棕猴脸,金紧箍,鹅黄僧衣+虎皮围裙,黑腕表,红色手机)",
       "M2": "猪八戒(粉灰猪头,大耳长吻,藏青僧衣敞怀露肚,大念珠)"}
FF_CAST = {"shot_001": ["M2"], "shot_003": ["M2"], "shot_008": ["M1"]}
OTS = {"shot_001", "shot_003"}
REMAP = "注意:运动描述里的'寸头男/深墨绿衬衫寸头男'在画面中是孙悟空,'花衬衫男/黑底白花纹衬衫男'是猪八戒,动作表情照描述执行。"
STYLE = ("photorealistic live-action night market, neon bokeh, shallow depth of field; the mythical "
         "characters are movie-grade CG creatures seamlessly composited into live footage, realistic fur "
         "and skin detail, like a fantasy blockbuster")

# 置顶强化口型锁(上一轮版本失败:惊呼/大笑状空嘴张开)
TOP_LOCK = {
    "shot_001": "最高优先级铁律:猪八戒是哑剧表演,全片段双唇要么闭合、要么正含着食物咀嚼,"
                "任何时刻都严禁空嘴张开、惊呼、说话;惊讶情绪只允许用瞪眼、挑眉、身体前倾表达,嘴巴绝不参与。",
    "shot_003": "最高优先级铁律:猪八戒是哑剧表演,全片段双唇要么闭合、要么正含着食物咀嚼,"
                "任何时刻都严禁空嘴大张、惊呼、说话;嫌弃情绪只允许用撇嘴(闭着)、斜眼、摇头表达。",
    "shot_008": "最高优先级铁律:孙悟空是哑剧表演,全片段双唇始终保持贴合闭拢,严禁张嘴、严禁露齿大笑、严禁说话;"
                "甜蜜得意只允许用眯眼、闭嘴上扬的嘴角、轻晃脑袋表达。",
}

def build_prompt(sid, sp):
    parts = [TOP_LOCK[sid]]
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
    parts.append(TOP_LOCK[sid])  # 首尾双置提高权重
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
    for sid in ["shot_001", "shot_003", "shot_008"]:
        sh = shots[sid]
        kf = Path(IM) / f"r4k4_{sid}.png"
        dur = min(15, max(2, math.ceil(sh["duration"]) + 1))
        name = f"r4v_{sid}_v2"
        if Path(f"{C}/{name}.mp4").is_file():
            print("EXIST", name, flush=True)
            continue
        prompt = build_prompt(sid, specs[sid])
        if not await submit_retry(name, str(kf), dur, prompt):
            continue
        if await wait_one(name):
            print("DONE", name, flush=True)
        await asyncio.sleep(10)
    print("R4-REDO-ALL-DONE", flush=True)

asyncio.run(main())

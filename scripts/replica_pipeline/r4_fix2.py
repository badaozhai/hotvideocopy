#!/usr/bin/env python
"""r4 二次返工:
- s001: 首帧本身张嘴(根因)→ gpt-image-2 以原首帧为参考改成闭嘴,再 I2V v3
- s003: v2 凭空多人 → 人数锁置顶重生成 v3
"""
import asyncio, json, math, subprocess, sys, time
from pathlib import Path

sys.path.insert(0, "/Users/suifei/works/hotvideocopy/src")
import os
os.chdir("/Users/suifei/works/hotvideocopy")
from hotvideocopy import video as V, images

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

REMAP = "注意:运动描述里的'寸头男/深墨绿衬衫寸头男'在画面中是孙悟空,'花衬衫男/黑底白花纹衬衫男'是猪八戒,动作表情照描述执行。"
STYLE = ("photorealistic live-action night market, neon bokeh, shallow depth of field; the mythical "
         "characters are movie-grade CG creatures seamlessly composited into live footage, realistic fur "
         "and skin detail, like a fantasy blockbuster")
LOCK_001 = ("最高优先级铁律:猪八戒是哑剧表演,首帧他的嘴是闭合的,全片段双唇必须始终保持闭合"
            "(或含食物咀嚼),严禁空嘴张开、惊呼、说话;惊讶只用瞪眼、挑眉、身体前倾表达。")
LOCK_003 = ("最高优先级铁律一:全画面自始至终只有猪八戒一位人物,他独自一人吃饭,同桌其他座位全部空置,"
            "严禁任何人类或其他角色进入画面、入座、出现在对焦范围内;背景远处路人必须始终重度虚化。"
            "最高优先级铁律二:猪八戒是哑剧表演,双唇闭合或含食物咀嚼,严禁空嘴张开说话。")

def base_prompt(sid):
    parts = []
    if sid in overrides:
        parts.append(overrides[sid])
    else:
        sp = specs[sid]
        if sp.get("camera"):
            parts.append(f"镜头:{sp['camera']}")
        if sp.get("i2v_prompt"):
            parts.append(sp["i2v_prompt"])
    parts.append("画面中自始至终只有1位主体人物:猪八戒(粉灰猪头,大耳长吻,藏青僧衣敞怀露肚,大念珠)。"
                 "人物的服装、发型、脸必须与首帧图完全一致并保持到片段结束,严禁变装换脸")
    parts.append("前景一侧的虚化肩背保持虚化,不得变清晰、不得露脸")
    parts.append(REMAP)
    return parts

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
    # 1) s001 首帧闭嘴修版
    cm = Path(IM) / "r4k_shot_001_cm.png"
    if not cm.is_file():
        await images.generate(
            "以参考图为唯一基准,输出一张几乎相同的画面:构图、机位、角色、服装、光线、背景霓虹虚化、"
            "前景鹅黄色虚化肩背全部原样保留,唯一的修改是:猪八戒张开的嘴改为完全闭合的抿嘴微笑,"
            "双唇贴合,不露口腔;惊讶感只保留在瞪大的眼睛和扶脸的手上。不得改动其他任何元素,"
            "不得新增人物,画面不带任何文字。",
            project_id=PID, refs=[f"{IM}/r4k_shot_001.png"],
            aspect="4:3", quality="2k", name="r4k_shot_001_cm")
        print("REDRAW-OK shot_001_cm", flush=True)
    cm4 = Path(IM) / "r4k4_shot_001_cm.png"
    if not cm4.is_file():
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(cm),
                        "-vf", "crop='min(iw,ih*4/3)':'min(ih,iw*3/4)',scale=1440:1080",
                        str(cm4)], check=True)

    jobs = [
        ("shot_001", str(cm4), LOCK_001),
        ("shot_003", f"{IM}/r4k4_shot_003.png", LOCK_003),
    ]
    for sid, kf, lock in jobs:
        name = f"r4v_{sid}_v3"
        if Path(f"{C}/{name}.mp4").is_file():
            print("EXIST", name, flush=True)
            continue
        dur = min(15, max(2, math.ceil(shots[sid]["duration"]) + 1))
        parts = [lock] + base_prompt(sid) + [lock, "严禁任何新人物进入画面;背景路人保持虚化不清晰", STYLE]
        prompt = "; ".join(parts)
        if not await submit_retry(name, kf, dur, prompt):
            continue
        if await wait_one(name):
            print("DONE", name, flush=True)
        await asyncio.sleep(10)
    print("R4-FIX2-ALL-DONE", flush=True)

asyncio.run(main())

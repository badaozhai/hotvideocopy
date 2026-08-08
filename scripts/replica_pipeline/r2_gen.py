#!/usr/bin/env python
"""remake2 I2V:重绘首帧 + 运动 prompt(带身份/人数双锁),≥1s 的 shot 出 2 条备选,串行+退避,可续跑。"""
import asyncio, json, math, sys, time
from pathlib import Path

sys.path.insert(0, "/Users/suifei/works/hotvideocopy/src")
import os
os.chdir("/Users/suifei/works/hotvideocopy")
from hotvideocopy import video as V

PID = "dy_7377380038250958121"
WS = f"workspace/{PID}"
IM = f"{WS}/gen/images"
C = f"{WS}/gen/clips"
R2 = f"{WS}/remake2"
SP = "/private/tmp/claude-501/-Users-suifei-works-hotvideocopy/b362c3f4-3764-4d87-a046-feaccc127248/scratchpad"

shots = json.loads(Path(f"{R2}/shots.json").read_text())["shots"]
specs = {r["id"]: r for r in json.loads(Path(f"{SP}/r2_specs.json").read_text())}
ffr = {}
fp = Path(f"{R2}/ff_roster.json")
if fp.is_file():
    ffr = {r["id"]: r["ff_roster"] for r in json.loads(fp.read_text())}
overrides = {}
op = Path(f"{R2}/prompts.json")
if op.is_file():
    overrides = json.loads(op.read_text())

WHO = {"A": "黑衣武者(黑色中式立领盘扣练功服,寸头)",
       "B": "军官(墨绿呢料军装+红领章+棕色皮质武装带,寸头方阔脸)",
       "C": "紫衫青年(紫色绸缎中式上衣)"}
STYLE = ("Hollywood martial-arts blockbuster, photorealistic live-action, anamorphic cinematic look, "
         "dramatic rim lighting, deep dark-gold grading. 1930s Japanese dojo interior.")

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
    start = ffr.get(sh["id"], sp.get("roster", []))
    allc = list(dict.fromkeys(start + [c for c in sp.get("roster", []) if c not in start]))
    enter = [c for c in allc if c not in start]
    if start:
        parts.append(f"画面开始时只有{len(start)}人:" + "、".join(WHO[c] for c in start if c in WHO)
                     + "。人物的服装、发型、脸必须与首帧图完全一致并保持到片段结束,严禁变装"
                     + "(军官领章为纯红色无任何纹样/军衔杠,不得新增肩章绶带)")
        if enter:
            parts.append("镜头中途入画:" + "、".join(WHO[c] for c in enter if c in WHO)
                         + "。除上述人物外,严禁任何其他人物进入画面或出现在背景中")
        else:
            parts.append("全程严禁任何新人物进入画面或出现在背景中")
    else:
        parts.append("画面中没有任何人物,不得有人入画")
    parts.append("动作幅度克制,与原片方向一致;不改变机位设定")
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
    for sh in shots:
        sid = sh["id"]
        if sid == "shot_025":
            continue  # 空镜 I2V 屡次长人,放弃生成走装配端 Ken Burns
        sp = specs.get(sid)
        kf = Path(IM) / f"r2k_{sid}.png"
        if sp is None or not kf.is_file():
            print(f"SKIP {sid}", flush=True)
            continue
        dur = min(15, max(2, math.ceil(sh["duration"]) + 1))
        nvar = 2 if sh["duration"] >= 1.0 else 1
        prompt = build_prompt(sh, sp)
        for k in range(nvar):
            name = f"r2v_{sid}_v{k}"
            if Path(f"{C}/{name}.mp4").is_file():
                continue
            if not await submit_retry(name, str(kf), dur, prompt):
                continue
            if await wait_one(name):
                print("DONE", name, flush=True)
            await asyncio.sleep(10)
    print("R2-GEN-ALL-DONE", flush=True)

asyncio.run(main())

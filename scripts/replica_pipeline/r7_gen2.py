#!/usr/bin/env python
"""r7 补齐 s3-s7 视觉片段:讲话神态+手势,配音后期单独铺,无逐字要求。"""
import asyncio, sys, time
from pathlib import Path
sys.path.insert(0, "/Users/suifei/works/hotvideocopy/src")
import os
os.chdir("/Users/suifei/works/hotvideocopy")
from hotvideocopy import video as V

PID = "dy_7601404577615805307"
WS = f"workspace/{PID}"
SET = "豪华中式厅堂主位,金色屏风暖宫灯,港片大佬会客厅氛围,暖金色电影布光"
NW_LOCK = ("最高优先级铁律:牛魔王的头自始至终是深棕色牛头——粗壮弯牛角、金鼻环、牛耳,"
           "绝不允许变成人脸或其他生物;黑西装白衬衫金链与首帧完全一致保持到最后一帧。")
LOCK = ("人物的服装、发型、脸必须与首帧图完全一致并保持到片段结束,严禁变装换脸;"
        "严禁任何新人物或他人身体部位进入画面")
CG = "photorealistic; movie-grade CG creature, consistent identity, cinematic lighting"

SHOTS = [
    ("shot_003", 5, "牛魔王竖着两根手指对镜头外的听众沉稳讲话,嘴自然开合像在训话,顿了顿卖关子,"
                    "嘴角带一丝冷笑,幅度克制"),
    ("shot_004", 6, "牛魔王一只拳头缓缓砸进另一只手掌,眼神燃起狠劲,一字一句地对镜头外训话,"
                    "嘴自然开合,身体前倾一点"),
    ("shot_005", 4, "牛魔王竖起三根手指,神情沉下来,语重心长地对镜头外讲话,嘴自然开合"),
    ("shot_006", 4, "牛魔王手指轻点茶几桌面两下,像把话钉进桌子里,对镜头外缓缓讲话,嘴自然开合,"
                    "目光柔和了一分"),
    ("shot_007", 5, "牛魔王说完最后一个字闭上嘴,身体靠回椅背,端起紫砂茶杯呷了一口,眼神深远,"
                    "尘埃落定"),
]

async def submit_and_wait(name, kf, dur, prompt):
    for bo in [0, 60, 120, 240]:
        if bo:
            await asyncio.sleep(bo)
        try:
            await V.start(prompt, project_id=PID, image=kf, duration=dur,
                          aspect="16:9", resolution="1080p", name=name)
            break
        except Exception as e:
            print(f"RETRY {name} ({str(e)[:90]})", flush=True)
    else:
        return False
    t0 = time.time()
    while time.time() - t0 < 1200:
        await asyncio.sleep(25)
        for j in V.jobs(PID):
            if j["name"] == name:
                st = j.get("status")
                if st in ("done", "failed"):
                    return st == "done"
                try:
                    r = await V.get(j["request_id"])
                    if r.get("status") in ("done", "failed"):
                        return r.get("status") == "done"
                except Exception:
                    pass
                break
    print("TIMEOUT", name, flush=True)
    return False

async def main():
    for sid, dur, act in SHOTS:
        name = f"r7v_{sid}_m0"
        if Path(f"{WS}/gen/clips/{name}.mp4").is_file():
            print("EXIST", name, flush=True)
            continue
        kf = f"{WS}/gen/images/r7k_{sid}.png"
        prompt = "; ".join([NW_LOCK, act, LOCK, SET, CG])
        if await submit_and_wait(name, kf, dur, prompt):
            print("DONE", name, flush=True)
        await asyncio.sleep(8)
    print("R7-GEN2-DONE", flush=True)

asyncio.run(main())

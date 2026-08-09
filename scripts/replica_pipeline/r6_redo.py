#!/usr/bin/env python
import asyncio, sys, time
from pathlib import Path
sys.path.insert(0, "/Users/suifei/works/hotvideocopy/src")
import os
os.chdir("/Users/suifei/works/hotvideocopy")
from hotvideocopy import video as V

PID = "dy_7670154130531790757"
R6_ENV = "巨轮航行在星光天河上,晚霞与银河交融,明月高悬,衣袂与缆绳被风吹动"
PIG_LOCK = ("最高优先级铁律:猪八戒的头自始至终是粉灰色的猪头——粉色猪鼻(两个鼻孔朝前)、"
            "一对下垂的大猪耳、长猪吻,绝不允许变成人脸、秃顶老人脸或任何其他生物;"
            "他的粉灰猪头、藏青僧衣、胸前大念珠必须与首帧完全一致保持到最后一帧。")
LOCK = ("人物的服装、发型、脸必须与首帧图完全一致并保持到片段结束,严禁变装换脸;"
        "严禁任何新人物或他人身体部位进入画面")
CG = ("photorealistic; the mythical characters are movie-grade CG creatures seamlessly "
      "composited into the environment, consistent identity")

JOBS = [
    ("r6k_shot_000", "r6v_shot_000_v1", 3,
     "船头经典姿势:嫦娥双臂展开迎风,广袖裙摆猎猎飞舞,猪八戒始终在她身后扶着她的腰,"
     "两人闭眼陶醉,动作幅度很小,身体只随船轻微起伏,相机缓慢推近;"
     "口型铁律:两人都不说话,嘴保持闭合微笑"),
    ("r6k_shot_001", "r6v_shot_001_v1", 4,
     "猪八戒双臂发力,把举过头顶的嫦娥朝船舷外用力一抛,嫦娥挥着手飞出画面右侧;"
     "抛完后八戒保持站立原地拍拍手,姿态不做其他大动作;嫦娥可短暂张嘴惊呼,八戒嘴闭合憨笑"),
]

async def main():
    for kf, name, dur, prompt in JOBS:
        out = Path(f"workspace/{PID}/gen/clips/{name}.mp4")
        if out.is_file():
            print("EXIST", name, flush=True)
            continue
        full = "; ".join([PIG_LOCK, prompt, LOCK, PIG_LOCK, R6_ENV, CG])
        img = f"workspace/{PID}/gen/images/{kf}.png"
        ok = False
        for bo in [0, 60, 120, 240]:
            if bo:
                await asyncio.sleep(bo)
            try:
                await V.start(full, project_id=PID, image=img, duration=dur,
                              aspect="16:9", resolution="1080p", name=name)
                ok = True
                break
            except Exception as e:
                print(f"RETRY {name} ({str(e)[:90]})", flush=True)
        if not ok:
            print("GIVEUP", name, flush=True)
            continue
        t0 = time.time()
        while time.time() - t0 < 1200:
            await asyncio.sleep(25)
            done = False
            for j in V.jobs(PID):
                if j["name"] == name:
                    st = j.get("status")
                    if st == "done":
                        done = True
                    elif st == "failed":
                        print("FAILED", name, flush=True)
                        done = True
                    else:
                        try:
                            r = await V.get(j["request_id"])
                            if r.get("status") in ("done", "failed"):
                                done = True
                                if r.get("status") == "failed":
                                    print("FAILED", name, flush=True)
                        except Exception:
                            pass
                    break
            if done:
                print("DONE", name, flush=True)
                break
        await asyncio.sleep(8)
    print("R6-REDO-DONE", flush=True)

asyncio.run(main())

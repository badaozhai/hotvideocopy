#!/usr/bin/env python
"""r5+r6 I2V 批量生成:首帧墙检通过后运行。串行+退避,可续跑,单备选。"""
import asyncio, math, sys, time
from pathlib import Path

sys.path.insert(0, "/Users/suifei/works/hotvideocopy/src")
import os
os.chdir("/Users/suifei/works/hotvideocopy")
from hotvideocopy import video as V

CG = ("photorealistic; the mythical characters are movie-grade CG creatures seamlessly "
      "composited into the environment, consistent identity")
LOCK = ("人物的服装、发型、脸必须与首帧图完全一致并保持到片段结束,严禁变装换脸;"
        "严禁任何新人物或他人身体部位进入画面")

R6_ENV = "巨轮航行在星光天河上,晚霞与银河交融,明月高悬,衣袂与缆绳被风吹动"
R5_ENV = "阴天高速公路,写实手机实拍质感,轻微手持晃动"

SHOTS = [
    # (pid, shot, dur, prompt)
    ("dy_7670154130531790757", "r6k_shot_000", 3,
     "船头经典姿势:嫦娥双臂展开迎风,广袖裙摆猎猎飞舞,猪八戒在身后扶着她的腰,两人闭眼陶醉,"
     "身体随船轻微起伏,相机缓慢推近;口型铁律:两人都不说话,嘴保持闭合微笑;" + R6_ENV),
    ("dy_7670154130531790757", "r6k_shot_001", 4,
     "猪八戒双臂发力,把举过头顶的嫦娥朝船舷外用力一抛,嫦娥双手挥舞着飞出画面右侧,"
     "八戒抛完拍拍手;嫦娥可短暂张嘴惊呼,八戒不说话嘴闭合憨笑;" + R6_ENV),
    ("dy_7670154130531790757", "r6k_shot_002", 3,
     "俯拍:半空坠落的嫦娥周身银色月光越来越亮,广袖展开,身体优雅转向,化作一道银色流光"
     "拖着光尾直冲天上明月,星光河面映出光路;唯美魔幻;" + R6_ENV),
    ("dy_7670154130531790757", "r6k_shot_003", 5,
     "猪八戒独自站在船艏,双臂完全张开如展翅,昂头畅快无声大笑,大耳朵扑扇,僧衣衣摆狂舞,"
     "相机缓慢推近,远处明月旁一道细银光划过;他不说话,只是大笑表情;" + R6_ENV),
    ("yt_R5OCCNIVwQ", "r5k_shot_000", 3,
     "全景:三人(猪八戒、白龙马、嫦娥)站路边轻松闲聊,有说有笑做手势;背景中远处白色教练车"
     "无人驾驶缓缓向后溜走,越溜越远,三人毫无察觉;" + R5_ENV),
    ("yt_R5OCCNIVwQ", "r5k_shot_001", 2,
     "近景:嫦娥猛回头看见远处溜车,瞪大眼睛惊恐张嘴尖叫,手指向远方,广袖甩动,踉跄半步;" + R5_ENV),
    ("yt_R5OCCNIVwQ", "r5k_shot_002", 3,
     "全景跟拍背影:孙悟空全力狂奔冲刺追赶远处溜走的白色教练车,大步流星越跑越快,僧衣飞舞,"
     "相机跟拍晃动,strong sprinting motion, he dashes at full speed;" + R5_ENV),
    ("yt_R5OCCNIVwQ", "r5k_shot_003", 3,
     "侧拍:白色教练车缓慢滑行中,孙悟空双手扒住敞开的车窗窗框,敏捷地翻身钻进车窗,"
     "像猴子攀树一样干净利落,下半身最后滑入车内,车继续缓慢滑行;" + R5_ENV),
    ("yt_R5OCCNIVwQ", "r5k_shot_004", 3,
     "中景:白色教练车稳稳刹停,车身轻微一顿,孙悟空从驾驶座车窗探出头和手臂,咧嘴得意大笑,"
     "朝画面外挥手;他不说话;" + R5_ENV),
]

async def submit_retry(name, pid, img, dur, prompt):
    for bo in [0, 60, 120, 240, 480, 600]:
        if bo:
            await asyncio.sleep(bo)
        try:
            await V.start(prompt, project_id=pid, image=img, duration=dur,
                          aspect="16:9", resolution="1080p", name=name)
            return True
        except Exception as e:
            print(f"RETRY {name} ({str(e)[:90]})", flush=True)
    print("GIVEUP", name, flush=True)
    return False

async def wait_one(pid, name, timeout=1500):
    t0 = time.time()
    while time.time() - t0 < timeout:
        await asyncio.sleep(28)
        for j in V.jobs(pid):
            if j["name"] == name:
                st = j.get("status")
                if st == "done":
                    return True
                if st == "failed":
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
    for pid, key, dur, prompt in SHOTS:
        kf0 = Path(f"workspace/{pid}/gen/images/{key}.png")
        # 竖版 9:16 首帧直接喂(grok 会拉伸装 16:9,装配端按几何检测压回)
        name = key.replace("k_", "v_") + "_v0"
        out = Path(f"workspace/{pid}/gen/clips/{name}.mp4")
        if out.is_file():
            print("EXIST", name, flush=True)
            continue
        if not kf0.is_file():
            print("NOKF", key, flush=True)
            continue
        full = "; ".join([prompt, LOCK, CG])
        if not await submit_retry(name, pid, str(kf0), dur, full):
            continue
        if await wait_one(pid, name):
            print("DONE", name, flush=True)
        await asyncio.sleep(8)
    print("R56-GEN-ALL-DONE", flush=True)

asyncio.run(main())

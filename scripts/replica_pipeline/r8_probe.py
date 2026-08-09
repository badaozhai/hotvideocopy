#!/usr/bin/env python
import asyncio, sys, time
sys.path.insert(0, "/Users/suifei/works/hotvideocopy/src")
import os
os.chdir("/Users/suifei/works/hotvideocopy")
from hotvideocopy import video as V

PID = "dy_7548028834538589492"
LINE = "悟空,你练的每一遍,都不白练"
prompt = "; ".join([
    "最高优先级铁律:画面是第一人称视角(徒弟的视角)的手持自拍式近景特写:菩提老祖"
    "(鹤发童颜,白发道髻木簪,雪白长须,月白道袍,手持拂尘)面对镜头说话,像长辈对着镜头"
    "开导晚辈;他的脸占画面主要位置,轻微手持晃动感;背景是斜阳下的山林,光斑虚化。",
    "声音铁律(最重要):他说的是地道的中国四川话(四川方言,西南官话,川渝口音),"
    "嗓音苍老温厚,慈祥里带着劲道,像七十岁的四川老先生摆龙门阵,语速从容;"
    "绝不能是标准普通话播音腔,绝不能是年轻人声音。",
    f'他用四川话对着镜头说 says in Sichuan dialect (四川话): "{LINE}"',
    f"台词铁律:台词内容必须逐字为「{LINE}」,用四川话发音,一个字不得增删;除这句外不说其他话。"
    "口型与台词精确同步。",
    "人物形象与首帧完全一致,严禁变脸;严禁其他人入画",
    "photorealistic, cinematic, warm sunset forest light"])

async def main():
    await V.start(prompt, project_id=PID,
                  image=f"workspace/{PID}/gen/images/cast_puti.png",
                  duration=6, aspect="16:9", resolution="1080p", name="r8_probe_sc0")
    t0 = time.time()
    while time.time() - t0 < 900:
        await asyncio.sleep(25)
        for j in V.jobs(PID):
            if j["name"] == "r8_probe_sc0":
                st = j.get("status")
                if st in ("done", "failed"):
                    print(st.upper())
                    return
                try:
                    r = await V.get(j["request_id"])
                    if r.get("status") in ("done", "failed"):
                        print(r.get("status").upper())
                        return
                except Exception:
                    pass
                break
    print("TIMEOUT")

asyncio.run(main())

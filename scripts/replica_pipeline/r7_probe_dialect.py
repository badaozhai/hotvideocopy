#!/usr/bin/env python
import asyncio, subprocess, sys, time
from pathlib import Path
sys.path.insert(0, "/Users/suifei/works/hotvideocopy/src")
import os
os.chdir("/Users/suifei/works/hotvideocopy")
from hotvideocopy import video as V

PID = "dy_7601404577615805307"
NAME = "r7w_dlg0_yl0"
LINE = "老牛我活了几万年,就悟出三句话"
prompt = "; ".join([
    "最高优先级铁律:牛魔王的头自始至终是深棕色牛头——粗壮弯牛角、金鼻环、牛耳,绝不允许变成人脸;"
    "黑西装白衬衫金链与首帧完全一致保持到最后一帧。",
    "声音铁律:他说的是中国湖南省沅陵县的方言(湘西沅陵话口音,西南官话腔调),"
    "嗓音非常低沉、浑厚、沙哑,威严的中年男声,像地方大佬训话,语速缓慢有分量,绝不能是年轻人声音,"
    "绝不能是标准普通话播音腔。",
    "牛魔王坐主位身体前倾,放下茶杯,对画面外的师徒缓缓开口",
    f'他用湖南沅陵方言说 says in Hunan Yuanling dialect (Chinese): "{LINE}"',
    f"台词铁律:台词内容必须逐字为「{LINE}」,用沅陵方言发音,一个字不得增删;除这句外不说其他话。"
    "口型与台词精确同步。",
    "人物服装发型脸与首帧完全一致;严禁新人物入画",
    "豪华中式厅堂主位,金色屏风暖宫灯,暖金色电影布光",
    "photorealistic; movie-grade CG creature, cinematic lighting"])

async def main():
    await V.start(prompt, project_id=PID, image=f"workspace/{PID}/gen/images/r7k_shot_000.png",
                  duration=6, aspect="16:9", resolution="1080p", name=NAME)
    t0 = time.time()
    while time.time() - t0 < 900:
        await asyncio.sleep(25)
        for j in V.jobs(PID):
            if j["name"] == NAME:
                st = j.get("status")
                if st == "done":
                    print("DONE")
                    return
                if st == "failed":
                    print("FAILED")
                    return
                try:
                    r = await V.get(j["request_id"])
                    if r.get("status") == "done":
                        print("DONE")
                        return
                    if r.get("status") == "failed":
                        print("FAILED")
                        return
                except Exception:
                    pass
                break
    print("TIMEOUT")

asyncio.run(main())

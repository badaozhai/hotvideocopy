#!/usr/bin/env python
import asyncio, json, sys, time
from pathlib import Path
sys.path.insert(0, "/Users/suifei/works/hotvideocopy/src")
import os
os.chdir("/Users/suifei/works/hotvideocopy")
from hotvideocopy import video as V

PID = "dy_7410349447718161701"
C = f"workspace/{PID}/gen/clips"
KF = f"workspace/{PID}/gen/images/r4k4_shot_001_cm.png"
SP = "/private/tmp/claude-501/-Users-suifei-works-hotvideocopy/b362c3f4-3764-4d87-a046-feaccc127248/scratchpad"
specs = {r["id"]: r for r in json.loads(Path(f"{SP}/r3_specs.json").read_text())}
sp = specs["shot_001"]

prompt = "; ".join([
    "最高优先级铁律一:猪八戒是哑剧表演,首帧他的嘴是闭合的,全片段双唇必须始终保持闭合,"
    "严禁空嘴张开、惊呼、说话;惊讶只用瞪大眼睛、身体微微前倾表达。",
    "最高优先级铁律二:除猪八戒本人外,画面里不得出现任何其他人的任何身体部位——"
    "对面人物的手、手臂、筷子、衣袖一律严禁伸入画面;前景一侧的虚化肩背保持原样虚化不动,"
    "不得变清晰、不得露脸、不得伸手。桌面上的食物保持原样,没有任何人去夹菜。",
    f"镜头:{sp.get('camera','')}",
    "猪八戒听到对面的话,瞪大眼睛露出难以置信的惊讶表情,一只手扶着脸颊,身体几乎不动,微微前倾",
    "画面中自始至终只有1位主体人物:猪八戒(粉灰猪头,大耳长吻,藏青僧衣敞怀露肚,大念珠)。"
    "人物的服装、发型、脸必须与首帧图完全一致并保持到片段结束,严禁变装换脸",
    "注意:运动描述里的'花衬衫男/黑底白花纹衬衫男'是猪八戒;严禁出现黑底白花纹的衣袖",
    "严禁任何新人物或身体部位进入画面;背景路人保持虚化不清晰",
    "photorealistic live-action night market, neon bokeh, shallow depth of field; the mythical "
    "characters are movie-grade CG creatures seamlessly composited into live footage",
])

async def main():
    name = "r4v_shot_001_v4"
    for bo in [0, 60, 120, 240]:
        if bo:
            await asyncio.sleep(bo)
        try:
            await V.start(prompt, project_id=PID, image=KF, duration=3,
                          aspect="16:9", resolution="1080p", name=name)
            break
        except Exception as e:
            print(f"RETRY ({str(e)[:90]})", flush=True)
    else:
        print("GIVEUP", flush=True)
        return
    t0 = time.time()
    while time.time() - t0 < 900:
        await asyncio.sleep(25)
        for j in V.jobs(PID):
            if j["name"] == name:
                st = j.get("status")
                if st == "done":
                    print("DONE", name, flush=True)
                    return
                if st == "failed":
                    print("FAILED", flush=True)
                    return
                try:
                    r = await V.get(j["request_id"])
                    if r.get("status") == "done":
                        print("DONE", name, flush=True)
                        return
                    if r.get("status") == "failed":
                        print("FAILED", flush=True)
                        return
                except Exception:
                    pass
                break
    print("TIMEOUT", flush=True)

asyncio.run(main())

#!/usr/bin/env python
"""r8 菩提老祖鼓励悟空:POV 口播对白 4 段(逐字锁+whisper回验) + 2 个毛手还礼镜。"""
import asyncio, json, re, subprocess, sys, time
from pathlib import Path

sys.path.insert(0, "/Users/suifei/works/hotvideocopy/src")
import os
os.chdir("/Users/suifei/works/hotvideocopy")
from hotvideocopy import video as V

PID = "dy_7548028834538589492"
WS = f"workspace/{PID}"
IM = f"{WS}/gen/images"
C = f"{WS}/gen/clips"

POV = ("画面保持第一人称视角自拍式构图:菩提老祖面对镜头、眼睛直视镜头说话,轻微手持晃动感,"
       "斜阳山林虚化背景")
ID_LOCK = ("最高优先级铁律:菩提老祖的形象与首帧完全一致——鹤发道髻木簪、白眉长须、月白道袍,"
           "严禁变脸变装;严禁任何其他人物入画")
VOICE = ("声音铁律:苍老温厚慈祥的老先生嗓音,七十岁长者的普通话,中气足而从容,"
         "像老师父把话慢慢讲进徒弟心里;绝不能是年轻人的声音,绝不能是粤语")
CG = "photorealistic, cinematic, warm sunset forest light"

DLG = [
    ("d0", "r8k_s0", 14, "悟空,你练的每一遍,都不白练。学一遍,长一遍本事;摔一跤,懂一分天高。",
     "菩提老祖眼含笑意对镜头缓缓开讲,拂尘轻搭臂弯,远处白鹤掠过天际"),
    ("d1", "r8k_s2", 15, "怕丢脸?脸面,是这天下最不值钱的东西。把人钉在原地的,是放不下那张脸。",
     "菩提老祖竖起手指点拨,神情语重心长,讲到后半句轻轻摇头,背景白鹿缓步走过"),
    ("d2", "r8k_s3", 12, "犹犹豫豫,瞻前顾后,才是真的白走一遭。你只管去练。",
     "菩提老祖大特写,目光深邃直视镜头,一字一句,说完向镜头微微颔首"),
    ("d3", "r8k_s0", 14, "记住为师的话:学不成,也赚一身筋骨。没有慧根,那就把一件事练上一万遍。",
     "菩提老祖神情郑重而温厚,说到最后抬手轻轻拍向镜头方向,像拍在徒弟肩上"),
]
SALUTES = [
    ("s1", "r8k_s1", 3, "画面下方悟空的两只毛茸茸猴手抱拳,向前深深一拱行礼;景深处菩提老祖"
     "含笑颔首;口型铁律:菩提老祖不说话,嘴保持闭合微笑"),
    ("s4", "r8k_s4", 3, "画面下方悟空的毛茸猴拳坚定地一握举起;菩提老祖抚须开怀大笑(无声画面,"
     "只有环境音),笑而不语"),
]

def norm(s):
    return re.sub(r"[^一-鿿]", "", s)

_model = None
def transcribe(clip):
    global _model
    from faster_whisper import WhisperModel
    if _model is None:
        _model = WhisperModel("large-v3", device="cpu", compute_type="int8")
    wav = f"{clip}.16k.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", clip, "-vn", "-ac", "1",
                    "-ar", "16000", wav], check=True)
    segs, _ = _model.transcribe(wav, language="zh", vad_filter=True,
        initial_prompt="菩提老祖开导悟空:你练的每一遍都不白练。脸面是天下最不值钱的东西。"
                       "犹犹豫豫才是白走一遭。没有慧根,那就把一件事练上一万遍。")
    out = [(s.start, s.end, s.text.strip()) for s in segs]
    Path(wav).unlink(missing_ok=True)
    return out

async def submit_and_wait(name, kf, dur, prompt):
    for bo in [0, 60, 120, 240, 480]:
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
    while time.time() - t0 < 1500:
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
    result = {"dlg": {}, "cut": {}}
    for key, kf, dur, line, act in DLG:
        want = norm(line)
        ok = None
        for att in range(3):
            name = f"r8v_{key}_t{att}"
            clip = f"{C}/{name}.mp4"
            if not Path(clip).is_file():
                prompt = "; ".join([
                    ID_LOCK, VOICE, act, POV,
                    f'他用苍老温厚的嗓音对镜头说 says in Chinese: "{line}"',
                    f"台词铁律:他说的台词必须逐字为「{line}」,一个字不得增删,不得改说其他任何话;"
                    "除这句台词外全程不再说话。口型与台词精确同步。",
                    CG])
                if not await submit_and_wait(name, f"{IM}/{kf}.png", dur, prompt):
                    continue
            segs = transcribe(clip)
            got = norm("".join(t for _, _, t in segs))
            span = (segs[-1][1] - segs[0][0]) if segs else 99
            print(f"ASR {name}: got={got} span={span:.2f}", flush=True)
            if got == want and span <= dur - 1.0:
                ok = (name, segs)
                break
            print(f"MISMATCH {name}", flush=True)
        if ok:
            name, segs = ok
            result["dlg"][key] = {"clip": name, "line": line,
                                  "start": segs[0][0], "end": segs[-1][1]}
            print(f"VERIFIED {key} -> {name}", flush=True)
        else:
            print(f"EXHAUSTED {key}", flush=True)
    for key, kf, dur, act in SALUTES:
        name = f"r8v_cut_{key}"
        if not Path(f"{C}/{name}.mp4").is_file():
            prompt = "; ".join([ID_LOCK, act, POV, CG])
            if not await submit_and_wait(name, f"{IM}/{kf}.png", dur, prompt):
                continue
        result["cut"][key] = {"clip": name}
        print(f"DONE {name}", flush=True)
    Path(f"{WS}/seg_r8.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
    print("R8-GEN-DONE", flush=True)

asyncio.run(main())

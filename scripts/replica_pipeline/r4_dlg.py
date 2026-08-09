#!/usr/bin/env python
"""结尾三句归还悟空:shot_010 说「你等个屁啊,你打错电话了」,shot_012 说「滚」后垮脸。
grok says-in-Chinese + 逐字锁,faster-whisper large-v3 回验,不合格自动重掷(最多3次)。"""
import asyncio, json, re, subprocess, sys, time
from pathlib import Path

sys.path.insert(0, "/Users/suifei/works/hotvideocopy/src")
import os
os.chdir("/Users/suifei/works/hotvideocopy")
from hotvideocopy import video as V

PID = "dy_7410349447718161701"
WS = f"workspace/{PID}"
IM = f"{WS}/gen/images"
C = f"{WS}/gen/clips"

WHO = "孙悟空(金棕猴脸,金紧箍,鹅黄僧衣+虎皮围裙,黑腕表,红色手机)"
STYLE = ("photorealistic live-action night market, neon bokeh, shallow depth of field; the mythical "
         "character is a movie-grade CG creature seamlessly composited into live footage")

JOBS = {
    "shot_010": {
        "kf": f"{IM}/r4k4_shot_010.png", "dur": 5,
        "line": "你等个屁啊,你打错电话了",
        "prompt": (
            "近景固定机位。孙悟空举着红色手机听电话,先是一脸不耐烦地翻白眼,随即忍无可忍,"
            "对着手机没好气地大声说 says in Chinese: \"你等个屁啊,你打错电话了\"。"
            "台词铁律:他说的台词必须逐字为「你等个屁啊,你打错电话了」,一个字不得增删,"
            "不得改成其他任何话;除这句台词外不说任何其他话。"
            "口型与台词精确同步。"),
    },
    "shot_012": {
        "kf": f"{IM}/r4k4_shot_012.png", "dur": 5,
        "line": "滚",
        "prompt": (
            "近景固定机位。孙悟空对着红色手机没好气地说一个字 says in Chinese: \"滚\","
            "然后把手机从耳边拿下来挂断,放到桌上,表情从不耐烦慢慢垮成想哭的苦瓜脸,"
            "嘴角下垮,眼神失落地看着桌上的菜,不再说话。"
            "台词铁律:全片段他只说这一个字「滚」,一个字不得增删,说完后嘴保持闭合,"
            "严禁任何其他说话型开合。口型与台词精确同步。"),
    },
}
COMMON = (f"画面中自始至终只有1位主体人物:{WHO}。人物的服装、发型、脸必须与首帧图完全一致"
          "并保持到片段结束,严禁变装换脸;严禁任何新人物或他人身体部位进入画面;"
          "背景路人保持虚化不清晰")

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
                                initial_prompt="夜市吃饭打电话的短剧对白:你等个屁啊,你打错电话了,滚。")
    out = [(s.start, s.end, s.text.strip()) for s in segs]
    Path(wav).unlink(missing_ok=True)
    return out

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
    while time.time() - t0 < 900:
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
    return False

async def main():
    result = {}
    for sid, jb in JOBS.items():
        want = norm(jb["line"])
        ok = None
        for att in range(3):
            name = f"r4v_{sid}_d{att}"
            clip = f"{C}/{name}.mp4"
            if not Path(clip).is_file():
                full = "; ".join([jb["prompt"], COMMON, STYLE])
                if not await submit_and_wait(name, jb["kf"], jb["dur"], full):
                    print(f"GENFAIL {name}", flush=True)
                    continue
            segs = transcribe(clip)
            got = norm("".join(t for _, _, t in segs))
            print(f"ASR {name}: {segs}", flush=True)
            if got == want:
                ok = (name, segs)
                break
            print(f"MISMATCH {name}: want={want} got={got}", flush=True)
        if ok:
            name, segs = ok
            result[sid] = {"clip": name,
                           "lines": [{"start": a, "end": b, "text": t} for a, b, t in segs]}
            print(f"VERIFIED {sid} -> {name}", flush=True)
        else:
            print(f"EXHAUSTED {sid}", flush=True)
    Path(f"{WS}/seg/dlg_tail.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1))
    print("R4-DLG-DONE", flush=True)

asyncio.run(main())

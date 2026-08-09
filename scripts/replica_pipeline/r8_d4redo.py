#!/usr/bin/env python
import asyncio, json, re, subprocess, sys, time
from pathlib import Path
sys.path.insert(0, "/Users/suifei/works/hotvideocopy/src")
import os
os.chdir("/Users/suifei/works/hotvideocopy")
from hotvideocopy import video as V

PID = "dy_7548028834538589492"
WS = f"workspace/{PID}"
C = f"{WS}/gen/clips"
LINE = "孺子可教也"

def norm(s):
    return re.sub(r"[^一-鿿]", "", s)

def transcribe(clip):
    from faster_whisper import WhisperModel
    m = WhisperModel("large-v3", device="cpu", compute_type="int8")
    wav = f"{clip}.16k.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", clip, "-vn", "-ac", "1",
                    "-ar", "16000", wav], check=True)
    segs, _ = m.transcribe(wav, language="zh", vad_filter=True,
                           initial_prompt="菩提老祖点头称赞:孺子可教也。")
    out = [(s.start, s.end, s.text.strip()) for s in segs]
    Path(wav).unlink(missing_ok=True)
    return out

async def waitfor(name):
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
    return False

async def main():
    want = norm(LINE)
    for att in range(2, 5):
        name = f"r8v_d4_t{att}"
        clip = f"{C}/{name}.mp4"
        if not Path(clip).is_file():
            prompt = "; ".join([
                "最高优先级铁律一:画面中绝对不能出现任何文字、字幕、花字、水印——这是纯画面,"
                "没有任何叠加文本。",
                "最高优先级铁律二:菩提老祖形象与首帧完全一致——鹤发道髻、白眉长须、月白道袍,"
                "严禁变脸变装;严禁其他人物入画。",
                "画面是第一人称视角(徒弟悟空的眼睛就是镜头):菩提老祖直视镜头缓缓点头说话,"
                "说完后,他举起手中的深色木戒尺,手臂向前伸,朝着镜头的正上方(即镜头前这位徒弟的"
                "头顶)轻轻敲了三下——每敲一下,戒尺都伸向镜头、离镜头更近,镜头随之轻微下沉晃动一下,"
                "像被敲到头顶;他绝不敲自己,戒尺始终朝镜头方向伸过来;敲完收尺,含笑注视镜头。",
                "声音铁律:苍老温厚慈祥的老先生普通话,绝不能年轻,绝不能是粤语",
                f'他边点头边说 says in Chinese: "{LINE}"',
                f"台词铁律:台词必须逐字为「{LINE}」,一个字不得增删;除这句外不说话。口型精确同步。",
                "photorealistic, cinematic, warm sunset forest light"])
            for bo in [0, 60, 120]:
                if bo:
                    await asyncio.sleep(bo)
                try:
                    await V.start(prompt, project_id=PID,
                                  image=f"{WS}/gen/images/r8k_s6.png", duration=8,
                                  aspect="16:9", resolution="1080p", name=name)
                    break
                except Exception as e:
                    print(f"RETRY {name} ({str(e)[:90]})", flush=True)
            if not await waitfor(name):
                print("GENFAIL", name, flush=True)
                continue
        segs = transcribe(clip)
        got = norm("".join(t for _, _, t in segs))
        print(f"ASR {name}: {segs}", flush=True)
        if got == want:
            seg = json.loads(Path(f"{WS}/seg_r8.json").read_text())
            seg["dlg"]["d4"] = {"clip": name, "line": LINE,
                                "start": segs[0][0], "end": segs[-1][1]}
            Path(f"{WS}/seg_r8.json").write_text(json.dumps(seg, ensure_ascii=False, indent=1))
            print(f"VERIFIED d4 -> {name}", flush=True)
            return
        print(f"MISMATCH {name}", flush=True)
    print("EXHAUSTED d4", flush=True)

asyncio.run(main())

#!/usr/bin/env python
"""r8 终修:①还礼镜改'菩提只点头不还礼'(重画s1首帧+两镜重生成) ②新增结尾戒尺镜。"""
import asyncio, json, re, subprocess, sys, time
from pathlib import Path
sys.path.insert(0, "/Users/suifei/works/hotvideocopy/src")
import os
os.chdir("/Users/suifei/works/hotvideocopy")
from hotvideocopy import images, video as V

PID = "dy_7548028834538589492"
WS = f"workspace/{PID}"
IM = f"{WS}/gen/images"
C = f"{WS}/gen/clips"
FRAMING = "本图为原创神话题材短剧的分镜素材,《西游记》为公版古典名著,角色为原创设计,仅用于影视美术参考。"
POV = ("画面为第一人称视角(徒弟悟空的视角)的手持自拍式构图,菩提老祖直视镜头,"
       "斜阳山林金色光斑虚化背景。")
CG = "photorealistic,电影质感,画面不带任何文字水印,只画描述的这一瞬间。"
ID_LOCK = ("最高优先级铁律:菩提老祖形象与首帧完全一致——鹤发道髻木簪、白眉长须、月白道袍,"
           "严禁变脸变装;严禁其他人物入画")
VOICE = ("声音铁律:苍老温厚慈祥的老先生嗓音,七十岁长者的普通话,中气足而从容;"
         "绝不能是年轻人的声音,绝不能是粤语")
PT = f"{IM}/cast_puti.png"
WD = f"{IM}/cast_wukong_dao_v2.png"

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

async def gen_video(name, kf, dur, prompt):
    if Path(f"{C}/{name}.mp4").is_file():
        print("EXIST", name, flush=True)
        return True
    for bo in [0, 60, 120, 240]:
        if bo:
            await asyncio.sleep(bo)
        try:
            await V.start(prompt, project_id=PID, image=kf, duration=dur,
                          aspect="16:9", resolution="1080p", name=name)
            ok = await waitfor(name)
            print(("DONE " if ok else "FAILED ") + name, flush=True)
            return ok
        except Exception as e:
            print(f"RETRY {name} ({str(e)[:90]})", flush=True)
    return False

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

async def main():
    # 1) s1 首帧 v2:菩提不碰徒弟的手
    if not Path(f"{IM}/r8k_s1v2.png").is_file():
        await images.generate(
            FRAMING + POV +
            "画面下缘,悟空毛茸茸的金棕色猴手(第2张参考图的手,青灰道袍袖口)从镜头下方入画,"
            "双手抱拳向前拱手行礼;景深处菩提老祖(第1张参考图)双手持拂尘自然站立,"
            "微微颔首含笑看着镜头方向——他的手不抬起、不触碰徒弟的手、不做任何回礼动作。"
            "只出现悟空的两只毛手,不出现悟空的脸。" + CG,
            project_id=PID, refs=[PT, WD], aspect="9:16", quality="2k", name="r8k_s1v2")
        print("OK r8k_s1v2", flush=True)
    # 2) 结尾戒尺镜首帧
    if not Path(f"{IM}/r8k_s6.png").is_file():
        await images.generate(
            FRAMING + POV +
            "菩提老祖(参考图)近景直视镜头,含笑点头,一只手举起一把深色老木戒尺(长条形旧木板尺),"
            "戒尺尺头朝向镜头上方,像要往镜头(徒弟的头顶)轻敲;另一只手持拂尘。神情慈爱中带着考校。" + CG,
            project_id=PID, refs=[PT], aspect="9:16", quality="2k", name="r8k_s6")
        print("OK r8k_s6", flush=True)

    # 3) 还礼镜重生成:菩提只点头
    await gen_video("r8v_cut_s1b", f"{IM}/r8k_s1v2.png", 3,
        "; ".join([ID_LOCK,
        "画面下方悟空的两只毛茸猴手抱拳向前一拱行礼;菩提老祖双手保持持拂尘不动,"
        "只是含笑缓缓点头两下作为回应,绝不抬手、绝不还礼、绝不触碰徒弟的手;"
        "口型铁律:不说话,嘴保持闭合微笑", POV, CG]))
    await gen_video("r8v_cut_s4b", f"{IM}/r8k_s4.png", 3,
        "; ".join([ID_LOCK,
        "画面下方悟空的毛茸猴拳坚定一握;菩提老祖只是笑着缓缓点头两下,双手保持原位"
        "(抚须的手继续抚须),绝不做回礼动作;口型铁律:不说话,笑而不语,嘴尽量闭合", POV, CG]))

    # 4) 结尾对白镜:孺子可教也 + 戒尺敲三下
    LINE = "孺子可教也"
    want = norm(LINE)
    result = None
    for att in range(3):
        name = f"r8v_d4_t{att}"
        clip = f"{C}/{name}.mp4"
        if not Path(clip).is_file():
            prompt = "; ".join([
                ID_LOCK, VOICE,
                "菩提老祖边缓缓点头边对镜头说话,说完后举起手中的深色木戒尺,"
                "朝镜头上方(徒弟的头顶)轻轻地、清脆地敲了三下——一下、两下、三下,"
                "每敲一下镜头轻微晃动一下;敲完收尺含笑注视镜头",
                f'他边点头边用苍老温厚的嗓音说 says in Chinese: "{LINE}"',
                f"台词铁律:台词必须逐字为「{LINE}」,一个字不得增删;除这句外不说话。口型精确同步。",
                POV, CG])
            if not await gen_video(name, f"{IM}/r8k_s6.png", 8, prompt):
                continue
        segs = transcribe(clip)
        got = norm("".join(t for _, _, t in segs))
        print(f"ASR {name}: {segs}", flush=True)
        if got == want:
            result = {"clip": name, "start": segs[0][0], "end": segs[-1][1]}
            print(f"VERIFIED d4 -> {name}", flush=True)
            break
        print(f"MISMATCH {name}", flush=True)
    seg = json.loads(Path(f"{WS}/seg_r8.json").read_text())
    seg["cut"]["s1"] = {"clip": "r8v_cut_s1b"}
    seg["cut"]["s4"] = {"clip": "r8v_cut_s4b"}
    if result:
        seg["dlg"]["d4"] = {"clip": result["clip"], "line": LINE,
                            "start": result["start"], "end": result["end"]}
    Path(f"{WS}/seg_r8.json").write_text(json.dumps(seg, ensure_ascii=False, indent=1))
    print("R8-FIX2-DONE", flush=True)

asyncio.run(main())

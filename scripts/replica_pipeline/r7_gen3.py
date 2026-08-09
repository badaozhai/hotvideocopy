#!/usr/bin/env python
"""r7 v2 方案:牛魔王 grok 现场开口(低沉威严中年男声+逐字锁+whisper回验),
每句话后切师徒五人点头反应镜(2个变体轮换)。产出 seg_r7v2.json。"""
import asyncio, json, re, subprocess, sys, time
from pathlib import Path

sys.path.insert(0, "/Users/suifei/works/hotvideocopy/src")
import os
os.chdir("/Users/suifei/works/hotvideocopy")
from hotvideocopy import video as V

PID = "dy_7601404577615805307"
WS = f"workspace/{PID}"
IM = f"{WS}/gen/images"
C = f"{WS}/gen/clips"

SET = "豪华中式厅堂主位,金色屏风暖宫灯,港片大佬会客厅氛围,暖金色电影布光"
NW_LOCK = ("最高优先级铁律:牛魔王的头自始至终是深棕色牛头——粗壮弯牛角、金鼻环、牛耳,"
           "绝不允许变成人脸或其他生物;黑西装白衬衫金链与首帧完全一致保持到最后一帧。")
VOICE = ("声音铁律(最重要):他的嗓音是极其低沉的男低音——六十岁老大哥的烟嗓,胸腔共鸣极重,"
         "沙哑苍劲,音调压到最低,extremely deep bass gravelly voice of an old boss;"
         "说的是中国湖南湘西方言(湘西话,西南官话腔调),语速缓慢一字一顿,"
         "绝不能是年轻人声音或标准普通话播音腔。")
LOCK = ("人物的服装、发型、脸必须与首帧图完全一致并保持到片段结束,严禁变装换脸;"
        "严禁任何新人物或他人身体部位进入画面")
CG = "photorealistic; movie-grade CG creatures, consistent identity, cinematic lighting"

DLG = [
    ("dlg0", "r7k_shot_000", 9, "老牛我活了几万年,就悟出三句话",
     "牛魔王坐主位身体前倾,放下茶杯,对画面外的师徒缓缓开口"),
    ("dlg1", "r7k_shot_002", 13, "第一,最硬的队伍就一句话——天塌下来一起扛,不是回洞里互相甩锅",
     "牛魔王竖起一根手指郑重开讲,讲到后半句手掌在空中一劈,眼神锐利"),
    ("dlg2", "r7k_shot_004", 13, "第二,最好的兄弟就一句话——打不过的妖怪一起上,不是出事了站着看热闹",
     "牛魔王竖起两根手指,讲到后半句一只拳头砸进另一只手掌,眼神燃起狠劲"),
    ("dlg3", "r7k_shot_005", 13, "第三,最顶的师徒就一件事——陪着徒弟把路走完,不是站在路边念紧箍咒",
     "牛魔王竖起三根手指,神情沉下来语重心长,讲到最后手指轻点茶几桌面"),
]
NODS = [
    ("nod_a", "五人同时表情严肃地缓缓点头两下,像小弟听懂了大佬训话;悟空抱臂点头,八戒停下瓜子点头,"
              "唐僧扶了下墨镜点头,沙僧沉沉颔首,白龙马矜持地点头;口型铁律:所有人嘴保持闭合,严禁说话"),
    ("nod_b", "五人再次表情严肃地齐齐点头,幅度比上次更深一点,彼此对视一眼再看回主位方向;"
              "口型铁律:所有人嘴保持闭合,严禁说话型开合,严肃认同的神情"),
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
        initial_prompt="牛魔王训话:老牛我活了几万年,就悟出三句话。最硬的队伍,天塌下来一起扛,"
                       "不是回洞里互相甩锅。最好的兄弟,打不过的妖怪一起上。最顶的师徒,"
                       "陪着徒弟把路走完,不是站在路边念紧箍咒。")
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
    result = {"dlg": {}, "nod": {}}
    for key, kf, dur, line, act in DLG:
        want = norm(line)
        ok = None
        for att in range(3):
            name = f"r7w_{key}_t{att}"
            clip = f"{C}/{name}.mp4"
            if not Path(clip).is_file():
                prompt = "; ".join([
                    NW_LOCK, VOICE, act,
                    f'他用极低沉的湖南湘西方言说 says in a very deep bass Hunan Xiangxi dialect (Chinese): "{line}"',
                    f"台词铁律:他说的台词必须逐字为「{line}」,一个字不得增删,不得改说其他任何话;"
                    "除这句台词外全程不再说话。口型与台词精确同步。",
                    LOCK, SET, CG])
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
    for key, act in NODS:
        name = f"r7w_{key}"
        if not Path(f"{C}/{name}.mp4").is_file():
            prompt = "; ".join([act, LOCK, SET, CG])
            if not await submit_and_wait(name, f"{IM}/r7k_shot_001.png", 3, prompt):
                continue
        result["nod"][key] = {"clip": name}
        print(f"DONE {name}", flush=True)
    Path(f"{WS}/seg_r7v2.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
    print("R7-GEN3-DONE", flush=True)

asyncio.run(main())

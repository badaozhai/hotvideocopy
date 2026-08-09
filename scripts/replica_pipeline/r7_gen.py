#!/usr/bin/env python
"""r7 I2V:7 对白镜(逐字锁+whisper回验+时长校验,最多3掷)+1 反应镜(口型锁)。
产出 workspace/.../seg_r7.json:每镜 clip 名 + 台词片内时间。"""
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
Path(C).mkdir(parents=True, exist_ok=True)

SET = "豪华中式厅堂主位,金色屏风暖宫灯,港片大佬会客厅氛围,暖金色电影布光"
NW_LOCK = ("最高优先级铁律:牛魔王的头自始至终是深棕色牛头——粗壮弯牛角、金鼻环、牛耳,"
           "绝不允许变成人脸或其他生物;黑西装白衬衫金链与首帧完全一致保持到最后一帧。")
LOCK = ("人物的服装、发型、脸必须与首帧图完全一致并保持到片段结束,严禁变装换脸;"
        "严禁任何新人物或他人身体部位进入画面")
CG = ("photorealistic; the mythical characters are movie-grade CG creatures, "
      "consistent identity, cinematic lighting")

# (shot, win 使用时长, gen 时长, 台词(None=反应镜), 动作描述)
SHOTS = [
    ("shot_000", 3.467, 5, "老牛我活了几万年,就悟出三句话",
     "牛魔王坐主位身体前倾,端着茶杯,对画面外的师徒开口说话,神态威严从容"),
    ("shot_001", 1.567, 3, None,
     "师徒五人安静听讲:悟空抱臂眉头微皱轻轻点头,八戒往嘴里丢了颗瓜子咀嚼,唐僧纹丝不动,"
     "沙僧站姿如山,白龙马冷傲地瞥了一眼;口型铁律:除八戒咀嚼外,所有人嘴保持闭合,"
     "严禁任何说话型开合,情绪只用眉眼表达"),
    ("shot_002", 7.433, 9, "第一,最硬的队伍就一句话——天塌下来一起扛,不是回洞里互相甩锅",
     "牛魔王放下茶杯竖起一根手指,郑重开讲,讲到后半句手掌在空中一劈,眼神锐利"),
    ("shot_003", 3.767, 5, "第二,最好的兄弟就一句话",
     "牛魔王竖起两根手指,嘴角带一丝冷笑,顿了顿卖个关子"),
    ("shot_004", 4.567, 6, "打不过的妖怪一起上,不是出事了看热闹",
     "牛魔王一只拳头砸进另一只手掌,眼神燃起狠劲,一字一句地说"),
    ("shot_005", 2.4, 4, "第三,最顶的师徒就一件事",
     "牛魔王竖起三根手指,神情沉下来,语重心长"),
    ("shot_006", 2.9, 4, "陪着徒弟把路走完",
     "牛魔王手指轻点茶几桌面,像把话钉进桌子里,目光柔和了一分"),
    ("shot_007", 3.867, 5, "而不是站在路边念紧箍咒",
     "牛魔王说完最后一个字,身体靠回椅背,端起茶杯呷了一口,尘埃落定"),
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
        initial_prompt="牛魔王讲人生道理:最硬的队伍,天塌下来一起扛;最好的兄弟,打不过的妖怪一起上;最顶的师徒,陪着徒弟把路走完,不是站在路边念紧箍咒。")
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
    while time.time() - t0 < 1200:
        await asyncio.sleep(25)
        for j in V.jobs(PID):
            if j["name"] == name:
                st = j.get("status")
                if st in ("done", "failed"):
                    if st == "failed":
                        print("FAILED", name, flush=True)
                    return st == "done"
                try:
                    r = await V.get(j["request_id"])
                    if r.get("status") in ("done", "failed"):
                        if r.get("status") == "failed":
                            print("FAILED", name, flush=True)
                        return r.get("status") == "done"
                except Exception:
                    pass
                break
    print("TIMEOUT", name, flush=True)
    return False

async def main():
    result = {}
    for sid, win, dur, line, act in SHOTS:
        kf = f"{IM}/r7k_{sid}.png"
        if not Path(kf).is_file():
            print("NOKF", sid, flush=True)
            continue
        if line is None:
            name = f"r7v_{sid}_v0"
            if not Path(f"{C}/{name}.mp4").is_file():
                prompt = "; ".join([act, LOCK, SET, CG])
                if await submit_and_wait(name, kf, dur, prompt):
                    print("DONE", name, flush=True)
            result[sid] = {"clip": name, "lines": []}
            continue
        want = norm(line)
        got_ok = None
        for att in range(3):
            name = f"r7v_{sid}_d{att}"
            clip = f"{C}/{name}.mp4"
            if not Path(clip).is_file():
                prompt = "; ".join([
                    NW_LOCK, act,
                    f'他对着镜头外的听众说 says in Chinese: "{line}"',
                    f"台词铁律:他说的台词必须逐字为「{line}」,一个字不得增删,不得改说其他任何话;"
                    "除这句台词外全程不再说话。口型与台词精确同步。语气:港片大佬,沉稳有力。",
                    LOCK, SET, CG])
                if not await submit_and_wait(name, kf, dur, prompt):
                    continue
            segs = transcribe(clip)
            got = norm("".join(t for _, _, t in segs))
            span = (segs[-1][1] - segs[0][0]) if segs else 99
            print(f"ASR {name}: {segs} span={span:.2f} win={win}", flush=True)
            if got == want and span <= win - 0.2:
                got_ok = (name, segs)
                break
            print(f"MISMATCH {name}: want={want} got={got} span={span:.2f}", flush=True)
        if got_ok:
            name, segs = got_ok
            result[sid] = {"clip": name,
                           "lines": [{"start": a, "end": b, "text": t} for a, b, t in segs]}
            print(f"VERIFIED {sid} -> {name}", flush=True)
        else:
            print(f"EXHAUSTED {sid}", flush=True)
    Path(f"{WS}/seg_r7.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
    print("R7-GEN-ALL-DONE", flush=True)

asyncio.run(main())

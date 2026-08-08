#!/usr/bin/env python
"""r4(悟空八戒版)装配:竖版 9:16 + 悟空对白镜原声(grok) + 铁扇公主画外 TTS(电话滤波)
+ BGM 伴奏 + ASS 字幕 + loudnorm → seg/final_wukong.mp4"""
import json, subprocess, sys
from pathlib import Path

import os
os.chdir("/Users/suifei/works/hotvideocopy/workspace/dy_7410349447718161701")
C = Path("gen/clips"); IM = Path("gen/images"); SEG = Path("seg"); TT = Path("gen/tts")

shots = json.loads((SEG / "shots.json").read_text())["shots"]
picks = json.loads((SEG / "picks_r4.json").read_text())
cx_map = json.loads((SEG / "crop_cx.json").read_text())

# 悟空台词片内时间(whisper 实测): shot_002 0.43-4.27; shot_004 由 SHOT004_T 注入
SHOT004_T = json.loads((SEG / "shot004_line.json").read_text())  # {"start":片内秒,"end":片内秒}
POS_002 = 9.83
POS_004 = 15.97

# 接电话时刻≈3.95s,女声一律在其后;惊不惊喜呀移到悟空第一句回话之后
FEMALE = [  # (文件, 开始秒, 字幕, atempo)
    ("f_00.mp3",  4.30, "今天我开工资啦", 1.0),
    ("f_01.mp3",  6.70, "我把你最喜欢的那个手办 我给你买了", 1.1),
    ("f_02.mp3", 14.10, "惊不惊喜呀", 1.0),
    ("cl_02.mp3", 18.60, "为什么要省啊 赚钱不就是给老公花的吗", 1.0),
    ("cl_03.mp3", 23.40, "今天你早点回家啊", 1.0),
    ("cl_04.mp3", 25.80, "明天带你去买新衣服", 1.0),
    ("cl_05.mp3", 28.60, "对了 我把你那个洗澡水都给你放好了", 1.0),
    ("cl_06.mp3", 32.80, "我在家等你哦", 1.0),
    ("cl_07.mp3", 38.40, "你等个屁啊", 1.0),
    ("cl_08.mp3", 40.40, "你打错电话了", 1.0),
    ("cl_09.mp3", 42.60, "滚", 1.0),
]

def dur_of(p):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                 "-of", "csv=p=0", str(p)], capture_output=True, text=True).stdout)

def ts(t):
    return f"{int(t//3600)}:{int(t%3600//60):02d}:{t%60:05.2f}"

subs = [(t0, min(t0 + dur_of(TT/f)/at + 0.15, 44.7), txt) for f, t0, txt, at in FEMALE]
subs.append((POS_002 + 0.43, POS_002 + 4.35, "你开工资了?你省着点花钱呢 花这么多干啥呀"))
subs.append((POS_004 + SHOT004_T["start"], min(POS_004 + SHOT004_T["end"] + 0.15, 44.7), "赚钱多不容易啊现在"))
subs.sort()
ass = ["[Script Info]", "ScriptType: v4.00+", "PlayResX: 1080", "PlayResY: 1920", "",
       "[V4+ Styles]",
       "Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, "
       "Outline, Shadow, Alignment, MarginL, MarginR, MarginV",
       "Style: zi,PingFang SC,72,&H00FFFFFF,&H00000000,&H80000000,-1,3,1,2,40,40,260", "",
       "[Events]", "Format: Layer, Start, End, Style, Text"]
for a, b, txt in subs:
    ass.append(f"Dialogue: 0,{ts(a)},{ts(b)},zi,{txt}")
(SEG / "subs_wk.ass").write_text("\n".join(ass))

segs = []
kb = []
for sh in shots:
    sid, dur = sh["id"], sh["duration"]
    src = C / f"r4v_{sid}_v{picks[sid]}.mp4"
    if not src.is_file():
        for k in range(2):
            alt = C / f"r4v_{sid}_v{k}.mp4"
            if alt.is_file():
                src = alt
                break
    if src.is_file():
        segs.append((str(src), dur, cx_map.get(sid, 0.5), sid, False))
    else:
        segs.append((str(IM / f"r4k4_{sid}.png"), dur, cx_map.get(sid, 0.5), sid, True))
        kb.append(sid)
total = sum(s_[1] for s_ in segs)
if kb:
    print("KB垫位(待池恢复替换):", kb)
print(f"segments={len(segs)} total={total:.3f}s")
assert abs(total - 44.77) < 0.06

inputs, filters, labels = [], [], []
for k, (src, dur, cx, sid, is_img) in enumerate(segs):
    if is_img:
        n = max(1, round(30 * dur))
        inputs += ["-loop", "1", "-t", f"{dur + 0.2}", "-i", src]
        filters.append(
            f"[{k}:v]crop='min(iw,ih*9/16)':ih:'min(max(iw*{cx}-ow/2,0),iw-ow)':0,"
            f"scale=2160:3840,zoompan=z='min(zoom+0.0010,1.10)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d={n}:s=1080x1920:fps=30,trim=duration={dur},setpts=PTS-STARTPTS,format=yuv420p[s{k}]")
    else:
        inputs += ["-i", src]
        filters.append(
            f"[{k}:v]tpad=stop_mode=clone:stop_duration=2,trim=duration={dur},"
            f"crop='min(iw,ih*4/3)':ih,"
            f"crop='min(iw,ih*9/16)':ih:'min(max(iw*{cx}-ow/2,0),iw-ow)':0,"
            f"scale=1080:1920,fps=30,setpts=PTS-STARTPTS,format=yuv420p[s{k}]")
    labels.append(f"[s{k}]")
nv = len(segs)
idx2 = next(k for k, s in enumerate(segs) if s[3] == "shot_002")
idx4 = next(k for k, s in enumerate(segs) if s[3] == "shot_004")

inputs += ["-i", "seg/demucs/htdemucs/full/no_vocals.wav"]
afx = [f"[{nv}:a]volume=-9dB,atrim=duration=44.77[bgm]"]
amix = ["[bgm]"]
# 悟空对白镜原声(全音量,L-cut 顺延到下一镜)
afx.append(f"[{idx2}:a]volume=1.0,adelay={int(POS_002*1000)}|{int(POS_002*1000)}[wk2]")
afx.append(f"[{idx4}:a]volume=1.0,adelay={int(POS_004*1000)}|{int(POS_004*1000)}[wk4]")
amix += ["[wk2]", "[wk4]"]
for j, (f, t0, _, at) in enumerate(FEMALE):
    idx = nv + 1 + j
    inputs += ["-i", str(TT / f)]
    tempo = f"atempo={at}," if abs(at - 1.0) > 1e-6 else ""
    afx.append(f"[{idx}:a]{tempo}highpass=f=300,lowpass=f=3400,volume=1.0,"
               f"adelay={int(t0*1000)}|{int(t0*1000)}[d{j}]")
    amix.append(f"[d{j}]")
afx.append("".join(amix) + f"amix=inputs={len(amix)}:normalize=0[mix]")
afx.append("[mix]loudnorm=I=-14:TP=-1.5:LRA=11[aout]")

filters.append("".join(labels) + f"concat=n={nv}:v=1:a=0[vc]")
filters.append("[vc]subtitles=seg/subs_wk.ass[vout]")

cmd = (["ffmpeg", "-y"] + inputs +
       ["-filter_complex", ";".join(filters + afx), "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "slow", "-crf", "17",
        "-c:a", "aac", "-b:a", "192k", "-t", "44.77", "seg/final_wukong.mp4"])
r = subprocess.run(cmd, capture_output=True, text=True)
if r.returncode:
    print(r.stderr[-1500:])
    sys.exit(1)
print("duration:", subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
      "-of", "csv=p=0", "seg/final_wukong.mp4"], capture_output=True, text=True).stdout.strip())
print("R4-ASSEMBLE-DONE")

#!/usr/bin/env python
"""r3 装配:13 镜按原剪辑点裁切拼接 + 原声 + ASS 字幕烧录 + loudnorm → seg/final.mp4"""
import json, subprocess, sys
from pathlib import Path

import os
os.chdir("/Users/suifei/works/hotvideocopy/workspace/dy_7410349447718161701")
C = Path("gen/clips")
IM = Path("gen/images")
SEG = Path("seg")

shots = json.loads((SEG / "shots.json").read_text())["shots"]
picks = json.loads((SEG / "picks.json").read_text()) if (SEG / "picks.json").is_file() else {}

SUBS = [
    (0.5, 3.2, "今天我开工资啦"),
    (3.5, 7.6, "我把你最喜欢的那个手办 我给你买了"),
    (9.9, 12.3, "惊不惊喜呀"),
    (12.6, 13.5, "你开工资了"),
    (13.6, 15.9, "你省着点花钱呢 你花这么多干啥呀"),
    (16.4, 17.7, "赚钱多不容易啊现在"),
    (18.0, 21.9, "为什么要省啊 赚钱不就是给老公花的吗"),
    (22.5, 24.4, "今天你早点回家啊"),
    (24.6, 26.4, "明天带你去买新衣服"),
    (27.0, 28.8, "对了 我把你那个洗澡水都给你放好了"),
    (29.0, 30.5, "我在家等你哦"),
    (38.3, 39.2, "你等个屁啊"),
    (40.1, 41.2, "你tm打错电话了"),
    (41.6, 42.6, "滚"),
]

def ts(t):
    h = int(t // 3600); m = int(t % 3600 // 60); s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"

ass = ["[Script Info]", "ScriptType: v4.00+", "PlayResX: 1440", "PlayResY: 1080", "",
       "[V4+ Styles]",
       "Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, "
       "Outline, Shadow, Alignment, MarginL, MarginR, MarginV",
       "Style: zi,PingFang SC,64,&H00FFFFFF,&H00000000,&H80000000,-1,3,1,2,40,40,60", "",
       "[Events]", "Format: Layer, Start, End, Style, Text"]
for a, b, txt in SUBS:
    ass.append(f"Dialogue: 0,{ts(a)},{ts(b)},zi,{txt}")
(SEG / "subs.ass").write_text("\n".join(ass))

segs = []
kb = []
for sh in shots:
    sid, dur = sh["id"], sh["duration"]
    src = None
    if sid in picks:
        cand = C / f"r3v_{sid}_v{picks[sid]}.mp4"
        src = cand if cand.is_file() else None
    if src is None:
        for k in range(3):
            cand = C / f"r3v_{sid}_v{k}.mp4"
            if cand.is_file():
                src = cand
                break
    if src is not None:
        segs.append((str(src), False, dur))
    else:
        kf = IM / f"r3k4_{sid}.png"
        segs.append((str(kf if kf.is_file() else sh["first_frame"]), True, dur))
        kb.append(sid)

total = sum(d for _, _, d in segs)
print(f"segments={len(segs)} total={total:.3f}s kenburns={kb}")
assert abs(total - 44.77) < 0.06, "时长不守恒"

inputs, filters, labels = [], [], []
for k, (src, is_img, dur) in enumerate(segs):
    if is_img:
        n = max(1, round(30 * dur))
        inputs += ["-loop", "1", "-t", f"{dur + 0.2}", "-i", src]
        filters.append(
            f"[{k}:v]scale=2880:2160:force_original_aspect_ratio=decrease,"
            f"pad=2880:2160:(ow-iw)/2:(oh-ih)/2,"
            f"zoompan=z='min(zoom+0.0010,1.10)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d={n}:s=1440x1080:fps=30,trim=duration={dur},setpts=PTS-STARTPTS,format=yuv420p[s{k}]")
    else:
        inputs += ["-i", src]
        filters.append(
            f"[{k}:v]tpad=stop_mode=clone:stop_duration=2,trim=duration={dur},"
            f"crop='min(iw,ih*4/3)':ih,"
            f"scale=1440:1080:force_original_aspect_ratio=decrease,"
            f"pad=1440:1080:(ow-iw)/2:(oh-ih)/2,fps=30,setpts=PTS-STARTPTS,format=yuv420p[s{k}]")
    labels.append(f"[s{k}]")
na = len(segs)
inputs += ["-i", "seg/audio/full.m4a"]
filters.append("".join(labels) + f"concat=n={na}:v=1:a=0[vc]")
filters.append("[vc]subtitles=seg/subs.ass[vout]")
filters.append(f"[{na}:a]loudnorm=I=-14:TP=-1.5:LRA=11[aout]")

cmd = (["ffmpeg", "-y"] + inputs +
       ["-filter_complex", ";".join(filters), "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "slow", "-crf", "17",
        "-c:a", "aac", "-b:a", "192k", "-t", "44.77", "seg/final.mp4"])
r = subprocess.run(cmd, capture_output=True, text=True)
if r.returncode:
    print(r.stderr[-1500:])
    sys.exit(1)
d = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                    "-of", "csv=p=0", "seg/final.mp4"], capture_output=True, text=True).stdout.strip()
print("final duration:", d)
print("R3-ASSEMBLE-DONE")

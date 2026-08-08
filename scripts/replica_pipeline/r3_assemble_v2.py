#!/usr/bin/env python
"""r3 装配 v2:竖版 9:16(1080x1920) + 重新配音(TTS 对白,电话女声加电话滤波)
+ 配乐(demucs 伴奏 -9dB) + ASS 字幕 + loudnorm → seg/final_v2.mp4"""
import json, subprocess, sys
from pathlib import Path

import os
os.chdir("/Users/suifei/works/hotvideocopy/workspace/dy_7410349447718161701")
C = Path("gen/clips"); IM = Path("gen/images"); SEG = Path("seg"); TT = Path("gen/tts")

shots = json.loads((SEG / "shots.json").read_text())["shots"]
picks = json.loads((SEG / "picks.json").read_text())
cx_map = json.loads((SEG / "crop_cx.json").read_text()) if (SEG / "crop_cx.json").is_file() else {}

# (文件, 开始秒, 是否电话音, 字幕文本)  — 先TTS后排轴,自然语速
LINES = [
    ("m1_00.mp3",  0.60, False, "今天我开工资啦"),
    ("m1_01.mp3",  3.50, False, "我把你最喜欢的那个手办 我给你买了"),
    ("m1_02.mp3",  9.90, False, "惊不惊喜呀"),
    ("cl_00.mp3", 12.20, True,  "你开工资了"),
    ("cl_01.mp3", 14.10, True,  "你省着点花钱呢 你花这么多干啥呀"),
    ("m1_03.mp3", 18.00, False, "赚钱多不容易啊现在"),
    ("cl_02.mp3", 21.00, True,  "为什么要省啊 赚钱不就是给老公花的吗"),
    ("cl_03.mp3", 25.20, True,  "今天你早点回家啊"),
    ("cl_04.mp3", 27.60, True,  "明天带你去买新衣服"),
    ("cl_05.mp3", 30.30, True,  "对了 我把你那个洗澡水都给你放好了"),
    ("cl_06.mp3", 34.40, True,  "我在家等你哦"),
    ("cl_07.mp3", 38.40, True,  "你等个屁啊"),
    ("cl_08.mp3", 40.40, True,  "你打错电话了"),
    ("cl_09.mp3", 42.50, True,  "滚"),
]

def dur_of(p):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                 "-of", "csv=p=0", str(p)], capture_output=True, text=True).stdout)

def ts(t):
    return f"{int(t//3600)}:{int(t%3600//60):02d}:{t%60:05.2f}"

ass = ["[Script Info]", "ScriptType: v4.00+", "PlayResX: 1080", "PlayResY: 1920", "",
       "[V4+ Styles]",
       "Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, "
       "Outline, Shadow, Alignment, MarginL, MarginR, MarginV",
       "Style: zi,PingFang SC,72,&H00FFFFFF,&H00000000,&H80000000,-1,3,1,2,40,40,260", "",
       "[Events]", "Format: Layer, Start, End, Style, Text"]
for f, t0, _, txt in LINES:
    ass.append(f"Dialogue: 0,{ts(t0)},{ts(min(t0 + dur_of(TT/f) + 0.15, 44.7))},zi,{txt}")
(SEG / "subs_v2.ass").write_text("\n".join(ass))

segs = []
for sh in shots:
    sid, dur = sh["id"], sh["duration"]
    segs.append((str(C / f"r3v_{sid}_v{picks[sid]}.mp4"), dur, cx_map.get(sid, 0.5)))
total = sum(d for _, d, _ in segs)
print(f"segments={len(segs)} total={total:.3f}s")
assert abs(total - 44.77) < 0.06

inputs, filters, labels = [], [], []
for k, (src, dur, cx) in enumerate(segs):
    inputs += ["-i", src]
    filters.append(
        f"[{k}:v]tpad=stop_mode=clone:stop_duration=2,trim=duration={dur},"
        f"crop='min(iw,ih*4/3)':ih,"
        f"crop='min(iw,ih*9/16)':ih:'min(max(iw*{cx}-ow/2,0),iw-ow)':0,"
        f"scale=1080:1920,fps=30,setpts=PTS-STARTPTS,format=yuv420p[s{k}]")
    labels.append(f"[s{k}]")
nv = len(segs)
# 音频输入: BGM 伴奏 + 14 条 TTS
inputs += ["-i", "seg/demucs/htdemucs/full/no_vocals.wav"]
afx = [f"[{nv}:a]volume=-9dB,atrim=duration=44.77[bgm]"]
amix = ["[bgm]"]
for j, (f, t0, phone, _) in enumerate(LINES):
    idx = nv + 1 + j
    inputs += ["-i", str(TT / f)]
    fx = "highpass=f=300,lowpass=f=3400,volume=1.0" if phone else "volume=1.0"
    afx.append(f"[{idx}:a]{fx},adelay={int(t0*1000)}|{int(t0*1000)}[d{j}]")
    amix.append(f"[d{j}]")
afx.append("".join(amix) + f"amix=inputs={len(amix)}:normalize=0[mix]")
afx.append("[mix]loudnorm=I=-14:TP=-1.5:LRA=11[aout]")

filters.append("".join(labels) + f"concat=n={nv}:v=1:a=0[vc]")
filters.append("[vc]subtitles=seg/subs_v2.ass[vout]")

cmd = (["ffmpeg", "-y"] + inputs +
       ["-filter_complex", ";".join(filters + afx), "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "slow", "-crf", "17",
        "-c:a", "aac", "-b:a", "192k", "-t", "44.77", "seg/final_v2.mp4"])
r = subprocess.run(cmd, capture_output=True, text=True)
if r.returncode:
    print(r.stderr[-1500:])
    sys.exit(1)
print("duration:", subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
      "-of", "csv=p=0", "seg/final_v2.mp4"], capture_output=True, text=True).stdout.strip())
print("R3-V2-DONE")

#!/usr/bin/env python
"""r7 终装配(配音单独铺方案):竖版 1080x1920。
- 视觉:s0=d0,s1=v0,s2=d0,s3-s7=m0;clip 原声全部静音(grok 即兴台词作废)
- 音频:edge-tts 云健配音 atempo 1.2 按排轴铺;loudnorm
- 字幕:按排轴,长句在逗号处按字数比例拆分"""
import json, re, subprocess, sys
from pathlib import Path
import os
os.chdir("/Users/suifei/works/hotvideocopy/workspace/dy_7601404577615805307")

shots = json.loads(Path("shots.json").read_text())["shots"]
C = Path("gen/clips"); TT = Path("gen/tts")
TOTAL = 29.967
PICK = {"shot_000": "d0", "shot_001": "v0", "shot_002": "d0", "shot_003": "m0",
        "shot_004": "m0", "shot_005": "m0", "shot_006": "m0", "shot_007": "m0"}

VO = [  # (文件, 开始秒, 字幕全文)
    ("v0.mp3", 0.40, "老牛我活了几万年,就悟出三句话,今天送给你们师徒"),
    ("v1.mp3", 5.65, "第一,最硬的队伍就一句话——天塌下来一起扛,而不是回了洞里互相甩锅"),
    ("v2.mp3", 12.55, "第二,最好的兄弟就一句话"),
    ("v3.mp3", 16.00, "打不过的妖怪一起上,而不是出了事站着看热闹"),
    ("v4.mp3", 21.00, "第三,最顶的师徒就一件事"),
    ("v56.mp3", 24.55, "陪着徒弟把这条路走完,而不是站在路边念紧箍咒"),
]
TEMPO = 1.2

def geometry(clip):
    r = subprocess.run(["ffmpeg", "-ss", "0.5", "-i", str(clip), "-frames:v", "5",
                        "-vf", "cropdetect=24:2", "-f", "null", "-"],
                       capture_output=True, text=True)
    m = re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", r.stderr)
    if not m:
        return "stretch"
    w, h, x, y = map(int, m[-1])
    return "pillar" if (x > 60 and w < 1700) else "stretch"

def dur_of(p):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                                 "format=duration", "-of", "csv=p=0", str(p)],
                                capture_output=True, text=True).stdout)

inputs, filters, labels = [], [], []
for k, sh in enumerate(shots):
    sid, dur = sh["id"], sh["duration"]
    clip = C / f"r7v_{sid}_{PICK[sid]}.mp4"
    assert clip.is_file(), clip
    mode = geometry(clip)
    pre = ("crop='min(iw,ih*9/16)':ih:(iw-ow)/2:0" if mode == "pillar"
           else "scale='trunc(ih*9/32)*2':ih")
    print(f"{sid}: {clip.name} {mode}")
    inputs += ["-i", str(clip)]
    filters.append(
        f"[{k}:v]tpad=stop_mode=clone:stop_duration=2,trim=duration={dur},"
        f"{pre},scale=1080:1920,fps=30,setpts=PTS-STARTPTS,format=yuv420p[s{k}]")
    labels.append(f"[s{k}]")
nv = len(shots)

afx, amix, subs = [], [], []
for j, (f, t0, txt) in enumerate(VO):
    idx = nv + j
    inputs += ["-i", str(TT / f)]
    ms = int(t0 * 1000)
    afx.append(f"[{idx}:a]atempo={TEMPO},volume=1.0,adelay={ms}|{ms}[d{j}]")
    amix.append(f"[d{j}]")
    span = dur_of(TT / f) / TEMPO
    parts = [p for p in re.split(r"[,,——]", txt) if p.strip()]
    total_ch = sum(len(p) for p in parts)
    cur = t0
    for p in parts:
        w = span * len(p) / total_ch
        subs.append((cur, min(cur + w + 0.1, TOTAL), p.strip()))
        cur += w
afx.append("".join(amix) + f"amix=inputs={len(amix)}:normalize=0[mix]")
afx.append("[mix]loudnorm=I=-14:TP=-1.5:LRA=11[aout]")

def ts(t):
    return f"{int(t//3600)}:{int(t%3600//60):02d}:{t%60:05.2f}"

ass = ["[Script Info]", "ScriptType: v4.00+", "PlayResX: 1080", "PlayResY: 1920", "",
       "[V4+ Styles]",
       "Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, "
       "Outline, Shadow, Alignment, MarginL, MarginR, MarginV",
       "Style: zi,PingFang SC,68,&H00FFFFFF,&H00000000,&H80000000,-1,3,1,2,40,40,260", "",
       "[Events]", "Format: Layer, Start, End, Style, Text"]
for a, b, txt in sorted(subs):
    ass.append(f"Dialogue: 0,{ts(a)},{ts(b)},zi,{txt}")
Path("subs_r7.ass").write_text("\n".join(ass))

filters.append("".join(labels) + f"concat=n={nv}:v=1:a=0[vc]")
filters.append("[vc]subtitles=subs_r7.ass[vout]")

cmd = (["ffmpeg", "-y"] + inputs +
       ["-filter_complex", ";".join(filters + afx), "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "slow", "-crf", "17",
        "-c:a", "aac", "-b:a", "192k", "-t", f"{TOTAL}", "final_niumowang.mp4"])
r = subprocess.run(cmd, capture_output=True, text=True)
if r.returncode:
    print(r.stderr[-1500:])
    sys.exit(1)
print("duration:", subprocess.run(["ffprobe", "-v", "error", "-show_entries",
      "format=duration", "-of", "csv=p=0", "final_niumowang.mp4"],
      capture_output=True, text=True).stdout.strip())
print("R7-ASSEMBLE2-DONE")

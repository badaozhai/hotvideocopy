#!/usr/bin/env python
"""r7 v2 终装配:牛魔王湘西话现场开口(口型同步)+ 每句后师徒点头镜。
竖版 1080x1920,无字幕。序列:dlg0→nod_a→dlg1→nod_b→dlg2→nod_a→dlg3→nod_b→呷茶。"""
import json, re, subprocess, sys
from pathlib import Path
import os
os.chdir("/Users/suifei/works/hotvideocopy/workspace/dy_7601404577615805307")

seg = json.loads(Path("seg_r7v2.json").read_text())
C = Path("gen/clips")
NOD_DUR = 2.0

def geometry(clip):
    r = subprocess.run(["ffmpeg", "-ss", "0.5", "-i", str(clip), "-frames:v", "5",
                        "-vf", "cropdetect=24:2", "-f", "null", "-"],
                       capture_output=True, text=True)
    m = re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", r.stderr)
    if not m:
        return "stretch"
    w, h, x, y = map(int, m[-1])
    return "pillar" if (x > 60 and w < 1700) else "stretch"

def clipdur(p):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                                 "format=duration", "-of", "csv=p=0", str(p)],
                                capture_output=True, text=True).stdout)

# (clip路径, 窗口起点, 使用时长, 音量)
SEQ = []
nods = ["nod_a", "nod_b", "nod_a", "nod_b"]
for i, key in enumerate(["dlg0", "dlg1", "dlg2", "dlg3"]):
    d = seg["dlg"][key]
    clip = C / f"{d['clip']}.mp4"
    cd = clipdur(clip)
    ws = max(0.0, d["start"] - 0.4)
    dur = min(d["end"] + 0.6, cd) - ws
    SEQ.append((clip, ws, dur, 1.0))
    nc = C / f"{seg['nod'][nods[i]]['clip']}.mp4"
    SEQ.append((nc, 0.3 if nods[i] == "nod_a" and i >= 2 else 0.0, NOD_DUR, 0.35))
SEQ.append((C / "r7v_shot_007_m0.mp4", 0.0, 3.0, 0.35))
TOTAL = sum(s[2] for s in SEQ)
print(f"segments={len(SEQ)} total={TOTAL:.2f}s")

inputs, filters, labels, afx, amix = [], [], [], [], []
pos = 0.0
for k, (clip, ws, dur, vol) in enumerate(SEQ):
    mode = geometry(clip)
    pre = ("crop='min(iw,ih*9/16)':ih:(iw-ow)/2:0" if mode == "pillar"
           else "scale='trunc(ih*9/32)*2':ih")
    print(f"  {clip.name} {mode} ws={ws} dur={dur:.2f}")
    inputs += ["-i", str(clip)]
    filters.append(
        f"[{k}:v]tpad=stop_mode=clone:stop_duration=2,"
        f"trim=start={ws:.3f}:duration={dur:.3f},setpts=PTS-STARTPTS,"
        f"{pre},scale=1080:1920,fps=30,format=yuv420p[s{k}]")
    labels.append(f"[s{k}]")
    ms = int(pos * 1000)
    afx.append(f"[{k}:a]atrim=start={ws:.3f}:duration={dur:.3f},asetpts=PTS-STARTPTS,"
               f"volume={vol},adelay={ms}|{ms}[a{k}]")
    amix.append(f"[a{k}]")
    pos += dur
nv = len(SEQ)
filters.append("".join(labels) + f"concat=n={nv}:v=1:a=0[vout]")
afx.append("".join(amix) + f"amix=inputs={len(amix)}:normalize=0[mix]")
afx.append("[mix]loudnorm=I=-14:TP=-1.5:LRA=11[aout]")

cmd = (["ffmpeg", "-y"] + inputs +
       ["-filter_complex", ";".join(filters + afx), "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "slow", "-crf", "17",
        "-c:a", "aac", "-b:a", "192k", "-t", f"{TOTAL:.3f}", "final_niumowang_v2.mp4"])
r = subprocess.run(cmd, capture_output=True, text=True)
if r.returncode:
    print(r.stderr[-1500:])
    sys.exit(1)
print("duration:", subprocess.run(["ffprobe", "-v", "error", "-show_entries",
      "format=duration", "-of", "csv=p=0", "final_niumowang_v2.mp4"],
      capture_output=True, text=True).stdout.strip())
print("R7-ASSEMBLE3-DONE")

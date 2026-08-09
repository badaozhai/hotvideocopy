#!/usr/bin/env python
"""r8 装配:菩提老祖 POV 口播。竖版 1080x1920,无字幕。
序列:d0 → 还礼1 → d1 → d2 → 还礼2 → d3 → 书法金句卡(2.5s Ken Burns)。"""
import json, re, subprocess, sys
from pathlib import Path
import os
os.chdir("/Users/suifei/works/hotvideocopy/workspace/dy_7548028834538589492")

seg = json.loads(Path("seg_r8.json").read_text())
C = Path("gen/clips")

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

SEQ = []  # (类型, 路径, ws, dur, vol)
def add_dlg(key):
    d = seg["dlg"][key]
    clip = C / f"{d['clip']}.mp4"
    cd = clipdur(clip)
    ws = max(0.0, d["start"] - 0.4)
    dur = min(d["end"] + 0.6, cd) - ws
    SEQ.append(("v", clip, ws, dur, 1.0))

def add_cut(key, dur=2.2):
    c = seg["cut"][key]
    SEQ.append(("v", C / f"{c['clip']}.mp4", 0.0, dur, 0.7))

# d2(犹犹豫豫段)用户判废:尾部面部漂移+句尾被切,整段弃用
add_dlg("d0"); add_cut("s1"); add_dlg("d1"); add_cut("s4"); add_dlg("d3")
add_dlg("d4")  # 孺子可教也 + 戒尺敲三下(整段含敲击动作,窗口放宽)
SEQ[-1] = ("v", SEQ[-1][1], SEQ[-1][2], min(SEQ[-1][3] + 2.4, clipdur(SEQ[-1][1]) - SEQ[-1][2]), 1.0)
SEQ.append(("img", Path("gen/images/r8k_card.png"), 0.0, 2.5, 0.0))
TOTAL = sum(s[3] for s in SEQ)
print(f"segments={len(SEQ)} total={TOTAL:.2f}s")

inputs, filters, labels, afx, amix = [], [], [], [], []
pos = 0.0
aidx = 0
for k, (typ, src, ws, dur, vol) in enumerate(SEQ):
    if typ == "img":
        n = max(1, round(30 * dur))
        inputs += ["-loop", "1", "-t", f"{dur + 0.2}", "-i", str(src)]
        filters.append(
            f"[{k}:v]scale=2160:3840,zoompan=z='min(zoom+0.0008,1.06)':x='iw/2-(iw/zoom/2)':"
            f"y='ih/2-(ih/zoom/2)':d={n}:s=1080x1920:fps=30,trim=duration={dur},"
            f"setpts=PTS-STARTPTS,format=yuv420p[s{k}]")
    else:
        mode = geometry(src)
        pre = ("crop='min(iw,ih*9/16)':ih:(iw-ow)/2:0" if mode == "pillar"
               else "scale='trunc(ih*9/32)*2':ih")
        print(f"  {src.name} {mode} ws={ws:.2f} dur={dur:.2f}")
        inputs += ["-i", str(src)]
        filters.append(
            f"[{k}:v]tpad=stop_mode=clone:stop_duration=2,"
            f"trim=start={ws:.3f}:duration={dur:.3f},setpts=PTS-STARTPTS,"
            f"{pre},scale=1080:1920,fps=30,format=yuv420p[s{k}]")
        ms = int(pos * 1000)
        afx.append(f"[{k}:a]atrim=start={ws:.3f}:duration={dur:.3f},asetpts=PTS-STARTPTS,"
                   f"volume={vol},adelay={ms}|{ms}[a{aidx}]")
        amix.append(f"[a{aidx}]")
        aidx += 1
    labels.append(f"[s{k}]")
    pos += dur
nv = len(SEQ)
filters.append("".join(labels) + f"concat=n={nv}:v=1:a=0[vout]")
afx.append("".join(amix) + f"amix=inputs={len(amix)}:normalize=0[mix]")
afx.append("[mix]loudnorm=I=-14:TP=-1.5:LRA=11[aout]")

cmd = (["ffmpeg", "-y"] + inputs +
       ["-filter_complex", ";".join(filters + afx), "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "slow", "-crf", "17",
        "-c:a", "aac", "-b:a", "192k", "-t", f"{TOTAL:.3f}", "final_puti.mp4"])
r = subprocess.run(cmd, capture_output=True, text=True)
if r.returncode:
    print(r.stderr[-1500:])
    sys.exit(1)
print("duration:", subprocess.run(["ffprobe", "-v", "error", "-show_entries",
      "format=duration", "-of", "csv=p=0", "final_puti.mp4"],
      capture_output=True, text=True).stdout.strip())
print("R8-ASSEMBLE-DONE")

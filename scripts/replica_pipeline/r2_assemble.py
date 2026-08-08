#!/usr/bin/env python
"""remake2 装配:每 shot 选素材(picks.json 指定 > v0)裁到原时长,缺素材降级 Ken Burns,
按原剪辑点拼接 + 原音轨 + loudnorm → remake2/final.mp4"""
import json, subprocess, sys
from pathlib import Path

import os
os.chdir("/Users/suifei/works/hotvideocopy/workspace/dy_7377380038250958121")
R2 = Path("remake2")
C = Path("gen/clips")
IM = Path("gen/images")

shots = json.loads((R2 / "shots.json").read_text())["shots"]
picks = json.loads((R2 / "picks.json").read_text()) if (R2 / "picks.json").is_file() else {}

segs = []  # (src, is_image, dur)
kb = []
for sh in shots:
    sid, dur = sh["id"], sh["duration"]
    src = None
    if sid in picks:
        cand = C / f"r2v_{sid}_v{picks[sid]}.mp4"
        src = cand if cand.is_file() else None
    if src is None:
        for k in range(3):
            cand = C / f"r2v_{sid}_v{k}.mp4"
            if cand.is_file():
                src = cand
                break
    if src is not None:
        segs.append((str(src), False, dur))
    else:
        kf = IM / f"r2k_{sid}.png"
        segs.append((str(kf if kf.is_file() else sh["first_frame"]), True, dur))
        kb.append(sid)

total = sum(d for _, _, d in segs)
print(f"segments={len(segs)} total={total:.3f}s kenburns={kb}")
assert abs(total - 60.0) < 0.06, "时长不守恒"

inputs, filters, labels = [], [], []
for k, (src, is_img, dur) in enumerate(segs):
    if is_img:
        n = max(1, round(30 * dur))
        inputs += ["-loop", "1", "-t", f"{dur + 0.2}", "-i", src]
        filters.append(
            f"[{k}:v]scale=3840:2160:force_original_aspect_ratio=decrease,"
            f"pad=3840:2160:(ow-iw)/2:(oh-ih)/2,"
            f"zoompan=z='min(zoom+0.0010,1.12)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d={n}:s=1920x1080:fps=30,trim=duration={dur},setpts=PTS-STARTPTS,format=yuv420p[s{k}]")
    else:
        inputs += ["-i", src]
        filters.append(
            f"[{k}:v]tpad=stop_mode=clone:stop_duration=2,trim=duration={dur},"
            f"scale=1920:1080:force_original_aspect_ratio=decrease,"
            f"pad=1920:1080:(ow-iw)/2:(oh-ih)/2,fps=30,setpts=PTS-STARTPTS,format=yuv420p[s{k}]")
    labels.append(f"[s{k}]")
na = len(segs)
inputs += ["-i", str(R2 / "audio" / "full.m4a")]
filters.append("".join(labels) + f"concat=n={na}:v=1:a=0[vout]")
filters.append(f"[{na}:a]loudnorm=I=-14:TP=-1.5:LRA=11[aout]")

cmd = (["ffmpeg", "-y"] + inputs +
       ["-filter_complex", ";".join(filters), "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "slow", "-crf", "17",
        "-c:a", "aac", "-b:a", "192k", "-t", "60", str(R2 / "final.mp4")])
r = subprocess.run(cmd, capture_output=True, text=True)
if r.returncode:
    print(r.stderr[-1500:])
    sys.exit(1)
d = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                    "-of", "csv=p=0", str(R2 / "final.mp4")],
                   capture_output=True, text=True).stdout.strip()
print("final duration:", d)
print("R2-ASSEMBLE-DONE")

#!/usr/bin/env python
"""remake2 CPU 侧:精武门 76-136s 切段 → 切 shot(>5s 拆段) → 抽首帧/采样帧 → 光流分级 → 抽音轨。"""
import json, math, subprocess, sys
from pathlib import Path

import os
os.chdir("/Users/suifei/works/hotvideocopy")
sys.path.insert(0, "src")
import cv2
from scenedetect import ContentDetector, detect

PID = "dy_7377380038250958121"
WS = Path(f"workspace/{PID}")
R2 = WS / "remake2"
FR = R2 / "frames"
for d in (FR, R2 / "audio"):
    d.mkdir(parents=True, exist_ok=True)

SRC60 = R2 / "source60.mp4"
if not SRC60.is_file():
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", "76", "-to", "136",
                    "-i", str(WS / "source.mp4"), "-c:v", "libx264", "-preset", "fast",
                    "-crf", "16", "-an", str(SRC60)], check=True)
subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", "76", "-to", "136",
                "-i", str(WS / "source.mp4"), "-vn", "-c:a", "aac", "-b:a", "192k",
                str(R2 / "audio" / "full.m4a")], check=True)

scenes = detect(str(SRC60), ContentDetector(threshold=27, min_scene_len=12))
raw = [(s.get_seconds(), e.get_seconds()) for s, e in scenes] or [(0.0, 60.0)]
# 补齐首尾
if raw[0][0] > 0.01:
    raw.insert(0, (0.0, raw[0][0]))
if raw[-1][1] < 59.9:
    raw.append((raw[-1][1], 60.0))
print(f"raw shots: {len(raw)}")

MAX = 5.0
shots = []
for i, (s, e) in enumerate(raw):
    n = max(1, math.ceil((e - s) / MAX))
    for k in range(n):
        a = s + (e - s) * k / n
        b = s + (e - s) * (k + 1) / n
        shots.append({"id": f"shot_{i:03d}" + (chr(97 + k) if n > 1 else ""),
                      "parent": i, "t_start": round(a, 3), "t_end": round(b, 3),
                      "duration": round(b - a, 3)})
print(f"after split: {len(shots)}")

def grab(t, out, max_side=0, q=2):
    cmd = ["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.3f}", "-i", str(SRC60),
           "-frames:v", "1", "-q:v", str(q)]
    if max_side:
        cmd += ["-vf", f"scale='min(iw,{max_side})':-2"]
    cmd.append(str(out))
    subprocess.run(cmd, check=True)

for sh in shots:
    s, e, d = sh["t_start"], sh["t_end"], sh["duration"]
    first = FR / f"{sh['id']}_first.png"
    grab(min(s + 0.05, e), first)
    sh["first_frame"] = str(first)
    n = 4
    ts = [s + 0.05 + (d - 0.1) * k / (n - 1) for k in range(n)]
    samples = []
    for k, t in enumerate(ts):
        p = FR / f"{sh['id']}_s{k}.jpg"
        grab(t, p, max_side=768, q=4)
        samples.append(str(p))
    sh["sample_frames"] = samples
    # 光流分级
    mags, prev = [], None
    for p in samples:
        img = cv2.imread(p, cv2.IMREAD_GRAYSCALE)
        if img is None:
            continue
        img = cv2.resize(img, (160, max(2, 160 * img.shape[0] // img.shape[1])))
        if prev is not None and prev.shape == img.shape:
            flow = cv2.calcOpticalFlowFarneback(prev, img, None, 0.5, 3, 15, 3, 5, 1.2, 0)
            mags.append(float(cv2.norm(flow, cv2.NORM_L2) / flow.size))
        prev = img
    m = sum(mags) / len(mags) if mags else 0.0
    sh["motion_level"] = "low" if m < 0.05 else ("medium" if m < 0.18 else "high")
    sh["motion_mag"] = round(m, 4)

(R2 / "shots.json").write_text(json.dumps({"shots": shots}, ensure_ascii=False, indent=1))
for sh in shots:
    print(sh["id"], f"[{sh['t_start']:6.2f}-{sh['t_end']:6.2f}]", f"{sh['duration']:4.1f}s",
          sh["motion_level"], sh["motion_mag"])
print("R2-EXTRACT-DONE")

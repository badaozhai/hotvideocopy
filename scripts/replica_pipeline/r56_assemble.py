#!/usr/bin/env python
"""r5(悟空救车 9s)+ r6(八戒天河 10s)装配:竖版 1080x1920。
几何逐 clip cropdetect:满幅=从 9:16 首帧拉伸成 16:9 → 横向压回;对称黑边 → 裁回。
r6 音频=原声 BGM 整轨;r5 音频=各 clip 环境原声接力。"""
import json, re, subprocess, sys
from pathlib import Path
import os
os.chdir("/Users/suifei/works/hotvideocopy")

def geometry(clip):
    r = subprocess.run(["ffmpeg", "-ss", "0.5", "-i", clip, "-frames:v", "5",
                        "-vf", "cropdetect=24:2", "-f", "null", "-"],
                       capture_output=True, text=True)
    m = re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", r.stderr)
    if not m:
        return "stretch"
    w, h, x, y = map(int, m[-1])
    # 对称竖黑边(pillarbox)判定:两侧均留边且宽度明显小于画布
    return "pillar" if (x > 60 and w < 1700) else "stretch"

def vfilter(k, mode, dur):
    # 目标:得到 9:16 竖幅再放大到 1080x1920
    if mode == "pillar":
        pre = "crop='min(iw,ih*9/16)':ih:(iw-ow)/2:0"
    else:  # 整幅由 9:16 拉伸而来 → 横向压回
        pre = "scale='trunc(ih*9/32)*2':ih"
    return (f"[{k}:v]tpad=stop_mode=clone:stop_duration=2,trim=duration={dur},"
            f"{pre},scale=1080:1920,fps=30,setpts=PTS-STARTPTS,format=yuv420p[s{k}]")

def assemble(pid, segs, audio_mode, out, total, bgm=None):
    inputs, filters, labels = [], [], []
    for k, (clip, dur) in enumerate(segs):
        mode = geometry(clip)
        print(f"  {Path(clip).name}: {mode}")
        inputs += ["-i", clip]
        filters.append(vfilter(k, mode, dur))
        labels.append(f"[s{k}]")
    nv = len(segs)
    afx, amix = [], []
    if audio_mode == "bgm":
        inputs += ["-i", bgm]
        afx.append(f"[{nv}:a]atrim=duration={total}[bgm]")
        amix.append("[bgm]")
    else:  # clips: 各镜环境原声按时间轴接力
        t = 0.0
        for k, (clip, dur) in enumerate(segs):
            ms = int(t * 1000)
            afx.append(f"[{k}:a]atrim=duration={dur},adelay={ms}|{ms}[a{k}]")
            amix.append(f"[a{k}]")
            t += dur
    afx.append("".join(amix) + f"amix=inputs={len(amix)}:normalize=0[mix]")
    afx.append("[mix]loudnorm=I=-14:TP=-1.5:LRA=11[aout]")
    filters.append("".join(labels) + f"concat=n={nv}:v=1:a=0[vc]")
    cmd = (["ffmpeg", "-y"] + inputs +
           ["-filter_complex", ";".join(filters + afx), "-map", "[vc]", "-map", "[aout]",
            "-c:v", "libx264", "-preset", "slow", "-crf", "17",
            "-c:a", "aac", "-b:a", "192k", "-t", f"{total}", out])
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        print(r.stderr[-1200:])
        sys.exit(1)
    d = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", out], capture_output=True, text=True).stdout.strip()
    print(f"{out}: {d}s")

which = sys.argv[1] if len(sys.argv) > 1 else "both"

if which in ("r6", "both"):
    print("== r6 八戒天河泰坦尼克 ==")
    W6 = "workspace/dy_7670154130531790757"
    picks6 = ["v1", "v1", "v0", "v0"]
    segs6 = [(f"{W6}/gen/clips/r6v_shot_{i:03d}_{picks6[i]}.mp4", d)
             for i, d in enumerate([2.0, 2.5, 2.0, 3.485])]
    assemble("r6", segs6, "bgm", f"{W6}/final_tianhe.mp4", 9.985,
             bgm=f"{W6}/bgm_full.m4a")

if which in ("r5", "both"):
    print("== r5 悟空救车 ==")
    W5 = "workspace/yt_R5OCCNIVwQ"
    segs5 = [(f"{W5}/gen/clips/r5v_shot_{i:03d}_v0.mp4", d)
             for i, d in enumerate([2.2, 1.3, 1.7, 1.8, 1.986])]
    assemble("r5", segs5, "clips", f"{W5}/final_jiuche.mp4", 8.986)

print("R56-ASSEMBLE-DONE")

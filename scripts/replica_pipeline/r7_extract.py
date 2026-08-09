#!/usr/bin/env python
import json, subprocess
from pathlib import Path
import os
os.chdir("/Users/suifei/works/hotvideocopy")
from scenedetect import ContentDetector, detect

WS = Path("workspace/dy_7601404577615805307")
FR = WS / "frames"
FR.mkdir(exist_ok=True)
SRC = WS / "source.mp4"
DUR = 29.977

scenes = detect(str(SRC), ContentDetector(threshold=27, min_scene_len=8))
raw = [(s.get_seconds(), e.get_seconds()) for s, e in scenes] or [(0.0, DUR)]
if raw[0][0] > 0.01:
    raw.insert(0, (0.0, raw[0][0]))
if raw[-1][1] < DUR - 0.1:
    raw.append((raw[-1][1], DUR))
shots = [{"id": f"shot_{i:03d}", "t_start": round(s, 3), "t_end": round(e, 3),
          "duration": round(e - s, 3)} for i, (s, e) in enumerate(raw)]
json.dump({"shots": shots}, open(WS / "shots.json", "w"), indent=1)
for sh in shots:
    s, e = sh["t_start"], sh["t_end"]
    for tag, t in [("first", min(s + 0.03, e)), ("mid", (s + e) / 2)]:
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.3f}", "-i", str(SRC),
                        "-frames:v", "1", "-q:v", "3", "-vf", "scale=360:-2",
                        str(FR / f"{sh['id']}_{tag}.jpg")], check=True)
print(json.dumps(shots, indent=1))
subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(SRC), "-vn", "-ac", "1",
                "-ar", "16000", str(WS / "audio16k.wav")], check=True)
from faster_whisper import WhisperModel
m = WhisperModel("large-v3", device="cpu", compute_type="int8")
segs, info = m.transcribe(str(WS / "audio16k.wav"), language="zh", vad_filter=True)
tr = [{"t": [round(x.start, 2), round(x.end, 2)], "text": x.text.strip()} for x in segs]
json.dump({"segments": tr}, open(WS / "transcript.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(tr, ensure_ascii=False, indent=1))
print("R7-EXTRACT-DONE")

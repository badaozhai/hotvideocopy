"""全局运动分类——运镜的 ground truth(VLM 猜运镜不可信,CV 信号说了算)。

相位相关(numpy FFT)估计相邻帧全局平移,按统计特征分类:
static / pan_l / pan_r / tilt_u / tilt_d / handheld / cut_or_fast / unknown

    .venv/bin/python -m hotvideocopy.motion <video|project_id>

读 shots.json,按 shot 输出 motion.json:
  [{"idx":0, "label":"handheld", "mean_px":1.8, "dir":[dx,dy], "confidence":0.7}, ...]
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

from .media import ffmpeg_bin
from .workspace import project_of, read_json, resolve_video, sub, write_json

FPS = 6          # 采样率:够分类,不重
W = 160          # 降采样宽度


def _extract_gray(video: Path, t0: float, t1: float, out_dir: Path) -> list[np.ndarray]:
    subprocess.run([ffmpeg_bin(), "-y", "-ss", f"{t0:.3f}", "-t", f"{max(0.3, t1 - t0):.3f}",
                    "-i", str(video), "-vf", f"fps={FPS},scale={W}:-2,format=gray",
                    str(out_dir / "g%04d.png")], check=True, capture_output=True)
    frames = []
    for f in sorted(out_dir.glob("g*.png")):
        frames.append(np.asarray(Image.open(f), dtype=np.float32))
        f.unlink()
    return frames


def _phase_shift(a: np.ndarray, b: np.ndarray) -> tuple[float, float, float]:
    """相位相关:返回 (dx, dy, 峰值锐度)。窗函数压边缘效应。"""
    h, w = a.shape
    win = np.outer(np.hanning(h), np.hanning(w))
    fa, fb = np.fft.rfft2(a * win), np.fft.rfft2(b * win)
    cross = fa * np.conj(fb)
    cross /= np.abs(cross) + 1e-9
    corr = np.fft.irfft2(cross, s=a.shape)
    peak = np.unravel_index(np.argmax(corr), corr.shape)
    dy, dx = peak
    if dy > h // 2:
        dy -= h
    if dx > w // 2:
        dx -= w
    sharp = float(corr.max() / (np.abs(corr).mean() + 1e-9))
    return float(dx), float(dy), sharp


def classify_shot(frames: list[np.ndarray]) -> dict:
    if len(frames) < 2:
        return {"label": "unknown", "mean_px": 0.0, "dir": [0, 0], "confidence": 0.0}
    dxs, dys, sharps = [], [], []
    for a, b in zip(frames, frames[1:]):
        dx, dy, sh = _phase_shift(a, b)
        dxs.append(dx); dys.append(dy); sharps.append(sh)
    dxs, dys = np.array(dxs), np.array(dys)
    mags = np.hypot(dxs, dys)
    mean_mag = float(mags.mean())
    mdx, mdy = float(dxs.mean()), float(dys.mean())
    conf = float(min(1.0, np.mean(sharps) / 50.0))

    # 分类:净位移 vs 抖动幅度
    net = float(np.hypot(mdx, mdy))
    jitter = float(np.hypot(dxs.std(), dys.std()))
    if mean_mag < 0.35:
        label = "static"
    elif np.mean(sharps) < 8:          # 相关峰糊:大运动/形变(可能推拉或快切)
        label = "cut_or_fast"
    elif net > 0.6 * mean_mag and abs(mdx) >= abs(mdy) * 1.3:
        label = "pan_r" if mdx < 0 else "pan_l"   # 画面右移=相机向左摇,取镜头方向
    elif net > 0.6 * mean_mag and abs(mdy) > abs(mdx) * 1.3:
        label = "tilt_d" if mdy < 0 else "tilt_u"
    elif jitter > 0.5:
        label = "handheld"
    else:
        label = "drift"
    return {"label": label, "mean_px": round(mean_mag, 2),
            "dir": [round(mdx, 2), round(mdy, 2)], "confidence": round(conf, 2)}


def analyze(video: str) -> dict:
    path = resolve_video(video)
    pid = project_of(path) or "scratch"
    shots = (read_json(sub(pid, "shots.json", create=False), {}) or {}).get("shots") or []
    if not shots:
        raise RuntimeError("缺 shots.json,先跑 scene_split")
    out = []
    with tempfile.TemporaryDirectory() as td:
        for s in shots:
            t0, t1 = s["t"]
            # 长镜只采样中段 4 秒(运镜通常均匀),省时间
            if t1 - t0 > 5:
                mid = (t0 + t1) / 2
                t0, t1 = mid - 2, mid + 2
            frames = _extract_gray(path, t0, t1, Path(td))
            r = classify_shot(frames)
            r["idx"] = s["idx"]
            out.append(r)
            print(f'#{s["idx"]:>2} [{s["t"][0]:>6.1f}-{s["t"][1]:>6.1f}] {r["label"]:<12} mean={r["mean_px"]:>5.2f}px conf={r["confidence"]}')
    result = {"video": str(path), "fps_sampled": FPS, "shots": out}
    if pid != "scratch":
        write_json(sub(pid, "motion.json"), result)
    return result


if __name__ == "__main__":
    analyze(sys.argv[1])

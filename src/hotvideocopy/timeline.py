"""装配：timeline.json → output.mp4。

这是工具箱里唯一「包 ffmpeg 复杂参数」的地方——精确裁切、统一规格、拼接、铺音。
timeline.json 由 Claude 写（内置 Write/Edit），本工具只忠实执行，不做创意判断。

## timeline.json schema

```jsonc
{
  "output": "output.mp4",          // 相对项目目录；可省略
  "size": "1080x1920",             // 目标画布；省略取第一段视频的尺寸
  "fps": 30,                       // 省略取第一段视频
  "video": [                       // 按序拼接。片段自带音轨一律丢弃（grok 音轨不要）
    { "src": "gen/clips/shot0.mp4", "trim": [0, 2.37] },   // trim 可省=整段
    { "src": "gen/clips/shot1.mp4" }
  ],
  "audio": [                       // 叠加铺音，全部混到一轨
    { "src": "gen/tts/line0.mp3", "at": 0.2 },             // at=落点秒
    { "src": "assets/bgm.mp3", "at": 0, "duration": 30,
      "gain_db": -12, "loop": true, "fade_in": 0.5, "fade_out": 1.5 },
    { "src": "x.wav", "trim": [3, 8], "at": 10 }           // 先裁再落
  ],
  "subtitles": "subs.ass"          // 可选，烧硬字幕（.ass/.srt）
}
```

- 裁切走重编码（-ss 前置 + 逐帧准），时长精确到帧——「生成向上取整、装配裁回 DNA 时间轴」
  说的就是这一步。
- 所有片段统一到画布：等比缩放 + 黑边补齐 + setsar=1 + 统一 fps，异源素材放心混拼。
- audio 混音 normalize=0，各轨音量互不牵连；BGM 压低用 gain_db。
"""

from __future__ import annotations

import shutil
from pathlib import Path

from .config import CONFIG
from .media import ffmpeg_bin, probe, run
from .workspace import project_dir, project_of, read_json, sub

_AUDIO_SR = 48000


def _resolve_asset(raw: str, pid: str) -> Path:
    """素材路径三连找：绝对/相对路径 → 项目目录相对 → 工作区相对。"""
    s = str(raw or "").strip()
    if not s:
        raise ValueError("timeline 里有素材缺 src")
    for cand in (Path(s).expanduser(),
                 project_dir(pid, create=False) / s if pid else None,
                 CONFIG.workspace / s):
        if cand and cand.is_file():
            return cand.resolve()
    raise FileNotFoundError(f"素材不存在：{s}")


def _locate_timeline(timeline: str) -> Path:
    s = str(timeline or "").strip()
    if not s:
        raise ValueError("缺少 timeline 参数（timeline.json 路径或 project_id）")
    p = Path(s).expanduser()
    if p.is_file():
        return p.resolve()
    for cand in (CONFIG.workspace / s, CONFIG.workspace / s / "timeline.json"):
        if cand.is_file():
            return cand.resolve()
    raise FileNotFoundError(f"找不到 timeline：{s}（不是文件，也不是含 timeline.json 的 project_id）")


def _esc_filter_path(p: Path) -> str:
    return str(p).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


async def assemble(timeline: str) -> dict:
    tpath = _locate_timeline(timeline)
    spec = read_json(tpath)
    if not isinstance(spec, dict):
        raise RuntimeError(f"timeline 不是合法 JSON 对象：{tpath}")

    pid = project_of(tpath)
    clips = spec.get("video") or []
    if not clips:
        raise RuntimeError("timeline.video 为空——至少要有一段视频")

    warnings: list[str] = []
    tmp = sub(pid or "scratch", "gen", "assemble_tmp", create=True)
    tmp.mkdir(exist_ok=True)

    # ── 目标规格：显式指定 > 第一段视频
    first_info = await probe(_resolve_asset(clips[0].get("src", ""), pid))
    size = str(spec.get("size") or "").strip()
    if size and "x" in size:
        w, h = (int(x) for x in size.lower().split("x", 1))
    else:
        w, h = int(first_info["width"]), int(first_info["height"])
    if not (w and h):
        raise RuntimeError("定不出目标尺寸：timeline.size 没写，第一段视频也读不出宽高")
    w, h = w - w % 2, h - h % 2
    fps = float(spec.get("fps") or first_info.get("fps") or 30)

    # ── pass 1：逐段精确裁切 + 统一规格（丢自带音轨）
    norm = (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps={fps}")
    parts: list[Path] = []
    timeline_clock = 0.0
    for i, c in enumerate(clips):
        src = _resolve_asset(c.get("src", ""), pid)
        sdur = float((await probe(src)).get("duration") or 0)
        trim = c.get("trim")
        args = ["-y"]
        frame_limit: int | None = None
        if trim:
            ss, to = float(trim[0]), float(trim[1])
            if to <= ss:
                raise RuntimeError(f"video[{i}] trim 起止颠倒：{trim}")
            if sdur and to > sdur + 0.05:
                warnings.append(f"video[{i}] trim 到 {to}s 但素材只有 {sdur}s，按素材末尾截断")
            requested = to - ss
            # 30fps 无法表示 4.55 这样的非整数帧时长。按累计时间取帧边界，
            # 把半帧误差分摊到相邻片段，避免25镜逐段向上取整后累积漂移。
            start_frame = round(timeline_clock * fps)
            timeline_clock += requested
            end_frame = round(timeline_clock * fps)
            frame_limit = max(1, end_frame - start_frame)
            args += ["-ss", f"{ss:.3f}", "-i", str(src)]
        else:
            args += ["-i", str(src)]
        part = tmp / f"clip_{i:03d}.mp4"
        frame_args = ["-frames:v", str(frame_limit)] if frame_limit is not None else []
        rc, _, err = await run(ffmpeg_bin(), *args, *frame_args, "-vf", norm, "-an",
                               "-c:v", "libx264", "-crf", "18", "-preset", "fast",
                               "-pix_fmt", "yuv420p", str(part), timeout=1800)
        if rc != 0 or not part.is_file():
            raise RuntimeError(f"video[{i}] 裁切失败：{err[-300:]}")
        pdur = float((await probe(part)).get("duration") or 0)
        if pdur < 0.1:
            # 1-2 帧的碎片段会污染 concat 时间戳,整条成片时长塌缩(实案:1帧卡致 529s→143s)
            raise RuntimeError(f"video[{i}] 规格化后仅 {pdur:.3f}s(源 {src.name} 可能坏/参数错)——碎片段禁止入拼接")
        parts.append(part)

    # ── pass 2：concat demuxer 拼接（规格已统一，copy 即可）
    lst = tmp / "concat.txt"
    lst.write_text("".join(f"file '{p.name}'\n" for p in parts), encoding="utf-8")
    silent = tmp / "silent.mp4"
    rc, _, err = await run(ffmpeg_bin(), "-y", "-f", "concat", "-safe", "0",
                           "-i", str(lst), "-c", "copy", str(silent), timeout=1800)
    if rc != 0:
        raise RuntimeError(f"拼接失败：{err[-300:]}")
    vdur = float((await probe(silent)).get("duration") or 0)

    # ── pass 3：铺音（可选）+ 烧字幕（可选）→ 成片
    out_rel = str(spec.get("output") or "output.mp4")
    out = Path(out_rel).expanduser()
    if not out.is_absolute():
        out = (project_dir(pid) if pid else CONFIG.workspace / "scratch") / out_rel
    out.parent.mkdir(parents=True, exist_ok=True)

    tracks = spec.get("audio") or []
    if isinstance(tracks, str) and tracks.upper().startswith("AUTO"):
        # 自动铺音:每段视频自带原声按其时间位置落轨(无音轨的卡自动跳过)——1:1 复刻标配
        tracks = []
        at = 0.0
        for c in clips:
            csrc = _resolve_asset(c.get("src", ""), pid)
            cinfo = await probe(csrc)
            cdur = (float(c["trim"][1]) - float(c["trim"][0])) if c.get("trim") else float(cinfo.get("duration") or 0)
            if cinfo.get("has_audio"):
                tracks.append({"src": c["src"], "trim": c.get("trim") or [0, round(cdur, 3)], "at": round(at, 3)})
            at += cdur
    subs = str(spec.get("subtitles") or "").strip()

    args = ["-y", "-i", str(silent)]
    fparts: list[str] = []
    amaps: list[str] = []
    for j, a in enumerate(tracks):
        src = _resolve_asset(a.get("src", ""), pid)
        at = float(a.get("at") or 0)
        requested_duration = float(a.get("duration") or 0)
        if a.get("loop"):
            args += ["-stream_loop", "-1"]
        args += ["-i", str(src)]
        chain = [f"aresample={_AUDIO_SR}", "aformat=channel_layouts=stereo"]
        trim = a.get("trim")
        if trim:
            chain.append(f"atrim={float(trim[0]):.3f}:{float(trim[1]):.3f},asetpts=PTS-STARTPTS")
        if a.get("loop"):
            requested_duration = requested_duration or max(0.001, vdur - at)
            chain.append(f"atrim=0:{requested_duration:.3f}")
        elif requested_duration:
            chain.append(f"atrim=0:{requested_duration:.3f}")
        fade_in = max(0.0, float(a.get("fade_in") or 0))
        fade_out = max(0.0, float(a.get("fade_out") or 0))
        if fade_in:
            chain.append(f"afade=t=in:st=0:d={fade_in:.3f}")
        if fade_out:
            effective_duration = requested_duration
            if not effective_duration and trim:
                effective_duration = float(trim[1]) - float(trim[0])
            if effective_duration <= fade_out:
                raise RuntimeError(f"audio[{j}] fade_out 必须短于音轨时长")
            chain.append(
                f"afade=t=out:st={effective_duration - fade_out:.3f}:d={fade_out:.3f}"
            )
        gain = float(a.get("gain_db") or 0)
        if gain:
            chain.append(f"volume={gain}dB")
        at_ms = int(at * 1000)
        if at_ms:
            chain.append(f"adelay={at_ms}:all=1")
        fparts.append(f"[{j + 1}:a]{','.join(chain)}[a{j}]")
        amaps.append(f"[a{j}]")
    if tracks:
        # apad=whole_dur 会自己终止；千万别写 apad,atrim=0:D——atrim 不向上游发 EOF，
        # apad 无限产静音，muxer 永远收不到流结束，ffmpeg 100% CPU 空转（实案）
        chain = (f"{''.join(amaps)}amix=inputs={len(tracks)}:duration=longest:normalize=0,"
                 f"apad=whole_dur={vdur:.3f}")
        if spec.get("loudnorm", True):
            # 成片响度拉到短视频平台口径（约 -14 LUFS）；TTS/素材原始响度普遍偏小
            chain += ",loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000"
        fparts.append(chain + "[aout]")

    if subs:
        sp = _resolve_asset(subs, pid)
        fparts.append(f"[0:v]subtitles='{_esc_filter_path(sp)}'[vout]")
        vmap, vcodec = "[vout]", ["-c:v", "libx264", "-crf", "18", "-preset", "fast",
                                  "-pix_fmt", "yuv420p"]
    else:
        vmap, vcodec = "0:v", ["-c:v", "copy"]

    if fparts:
        args += ["-filter_complex", ";".join(fparts)]
    args += ["-map", vmap]
    if tracks:
        args += ["-map", "[aout]", "-c:a", "aac", "-b:a", "192k"]
    else:
        warnings.append("timeline.audio 为空，成片没有音轨")
    args += [*vcodec, "-movflags", "+faststart", "-t", f"{vdur:.3f}", str(out)]

    rc, _, err = await run(ffmpeg_bin(), *args, timeout=3600)
    if rc != 0 or not out.is_file():
        raise RuntimeError(f"成片输出失败：{err[-400:]}")

    shutil.rmtree(tmp, ignore_errors=True)
    info = await probe(out)
    return {
        "output": str(out),
        "project_id": pid,
        "clips": len(parts),
        "audio_tracks": len(tracks),
        "subtitles": bool(subs),
        "duration": info.get("duration"),
        "width": info.get("width"), "height": info.get("height"),
        "fps": info.get("fps"), "has_audio": info.get("has_audio"),
        "warnings": warnings,
    }

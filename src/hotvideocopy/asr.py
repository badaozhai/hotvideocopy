"""转写链路：抽音轨 → 人声分离（可选）→ faster-whisper → 说话人分离（可选）。

重依赖装到哪层用哪层，全部优雅降级：
- demucs 没装            → 直接用原始音轨转写（BGM 重的片准确率会掉，建议装）
- pyannote 没装 / 没 token → segments 不带 spk，单人口播片本来也不需要
- faster-whisper 没装     → 人话报错，提示装 asr extras

中间产物落 workspace/<pid>/asr/，按文件存在与否跳步——demucs 一跑几分钟，重跑不重算。
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys

from .config import CONFIG
from .media import ffmpeg_bin, probe, run
from .workspace import project_of, resolve_video, sub, write_json

# 模型进程内缓存：whisper 冷加载十几秒起步，同会话第二条片不该再等一次
_MODELS: dict = {}


def _has(mod: str) -> bool:
    try:
        return importlib.util.find_spec(mod) is not None
    except ModuleNotFoundError:  # 查 a.b 时连 a 都没有，find_spec 不返回 None 而是直接抛
        return False


async def transcribe(video: str, language: str = "", model: str = "",
                     vocals: bool = True, diarize: bool = True) -> dict:
    path = resolve_video(video)
    info = await probe(path)
    if not info.get("has_audio"):
        raise RuntimeError(f"视频没有音轨，没法转写：{path}")
    if not _has("faster_whisper"):
        raise RuntimeError("faster-whisper 未安装——先 `pip install -e '.[asr]'`"
                           "（首次运行还会自动下载模型权重，large-v3 约 3GB）")

    pid = project_of(path) or "scratch"
    adir = sub(pid, "asr", create=True)
    adir.mkdir(exist_ok=True)
    notes: list[str] = []

    # 1) 抽全质量音轨（demucs 吃 44.1k 立体声效果最好，别直接给它 16k mono）
    audio = adir / "audio.wav"
    if not audio.is_file():
        rc, _, err = await run(ffmpeg_bin(), "-y", "-i", str(path), "-vn",
                               "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le",
                               str(audio), timeout=600)
        if rc != 0:
            raise RuntimeError(f"抽音轨失败：{err[-300:]}")

    # 2) 人声分离
    wsrc, engine_vocals = audio, "raw"
    if vocals:
        if _has("demucs"):
            voc = adir / "demucs" / "htdemucs" / "audio" / "vocals.wav"
            if not voc.is_file():
                rc, _, err = await run(sys.executable, "-m", "demucs", "--two-stems", "vocals",
                                       "-n", "htdemucs", "-o", str(adir / "demucs"),
                                       str(audio), timeout=3600)
                if rc != 0 or not voc.is_file():
                    notes.append(f"demucs 分离失败，退回原始音轨：{err[-200:]}")
            if voc.is_file():
                wsrc, engine_vocals = voc, "demucs/htdemucs"
        else:
            notes.append("demucs 未安装，用原始音轨直接转写"
                         "（BGM 重的片建议装：pip install -e '.[asr]'）")

    # 3) 重采样成 whisper/pyannote 的 16k mono
    wav16 = adir / ("asr16k_vocals.wav" if engine_vocals != "raw" else "asr16k_raw.wav")
    if not wav16.is_file():
        rc, _, err = await run(ffmpeg_bin(), "-y", "-i", str(wsrc), "-ac", "1", "-ar", "16000",
                               "-c:a", "pcm_s16le", str(wav16), timeout=600)
        if rc != 0:
            raise RuntimeError(f"重采样失败：{err[-300:]}")

    # 4) 转写（同步重活丢线程，别把事件循环卡死）
    size = model or CONFIG.whisper_model
    segs, lang, lang_prob = await asyncio.to_thread(_whisper, str(wav16), size, language)

    # 5) 说话人分离
    speakers: list[str] = []
    engine_diar = "off"
    if diarize and segs:
        if not _has("pyannote.audio"):
            notes.append("pyannote.audio 未安装，跳过说话人分离（单人口播不受影响）")
        elif not CONFIG.hf_token:
            notes.append("未设置 HF_TOKEN，跳过说话人分离"
                         "（pyannote 模型是 gated，需要 HuggingFace token 并在模型页接受协议）")
        else:
            try:
                turns = await asyncio.to_thread(_diarize, str(wav16), CONFIG.hf_token)
                speakers = sorted({spk for _, _, spk in turns})
                _assign_speakers(segs, turns)
                engine_diar = "pyannote/speaker-diarization-3.1"
            except Exception as e:  # gated 协议没接受 / 下载失败——别让整个转写陪葬
                notes.append(f"说话人分离失败（转写结果不受影响）：{e}")

    result = {
        "video": str(path),
        "project_id": pid,
        "engine": {"asr": f"faster-whisper/{size}", "vocals": engine_vocals, "diarize": engine_diar},
        "language": lang,
        "language_prob": lang_prob,
        "speakers": speakers,
        "segments": segs,
        "notes": notes,
    }
    if pid != "scratch":
        result["file"] = write_json(sub(pid, "transcript.json"), result)
    return result


def _whisper(wav: str, size: str, language: str) -> tuple[list[dict], str, float]:
    from faster_whisper import WhisperModel

    m = _MODELS.get(("whisper", size))
    if m is None:
        m = WhisperModel(size, device="auto", compute_type="auto")
        _MODELS[("whisper", size)] = m

    # 默认按中文短视频给提示词（引导简体+规范标点）；明确指定其它语言时不加
    prompt = "以下是简体中文短视频的口播与对白，使用规范标点。" if language in ("", "zh") else None
    it, info = m.transcribe(wav, language=language or None, vad_filter=True,
                            initial_prompt=prompt, beam_size=5)
    segs = [{"t": [round(s.start, 2), round(s.end, 2)], "text": s.text.strip(), "spk": None}
            for s in it if s.text.strip()]
    return segs, info.language, round(float(info.language_probability or 0), 3)


def _diarize(wav: str, token: str) -> list[tuple[float, float, str]]:
    from pyannote.audio import Pipeline

    p = _MODELS.get("pyannote")
    if p is None:
        p = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", use_auth_token=token)
        _MODELS["pyannote"] = p
    ann = p(wav)
    return [(t.start, t.end, spk) for t, _, spk in ann.itertracks(yield_label=True)]


def _assign_speakers(segs: list[dict], turns: list[tuple[float, float, str]]) -> None:
    """每段配重叠时长最大的说话人。没重叠的保持 None（可能是纯 BGM 误出的段）。"""
    for s in segs:
        st, en = s["t"]
        best, best_ov = None, 0.0
        for ts, te, spk in turns:
            ov = min(en, te) - max(st, ts)
            if ov > best_ov:
                best, best_ov = spk, ov
        s["spk"] = best

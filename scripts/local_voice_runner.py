#!/usr/bin/env python3
"""Single-shot MLX-Audio runner. Invoked only inside the isolated runtime."""

from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from mlx_audio.tts.utils import load_model


def accepted_kwargs(callable_obj, values: dict) -> dict:
    signature = inspect.signature(callable_obj)
    if any(param.kind == inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values()):
        return {key: value for key, value in values.items() if value not in (None, "")}
    return {
        key: value
        for key, value in values.items()
        if key in signature.parameters and value not in (None, "")
    }


def first_audio(results) -> tuple[np.ndarray, int]:
    for result in results:
        audio = getattr(result, "audio", None)
        if audio is None and isinstance(result, dict):
            audio = result.get("audio")
        if audio is None:
            continue
        if hasattr(audio, "tolist"):
            audio = audio.tolist()
        rate = getattr(result, "sample_rate", None)
        if rate is None and isinstance(result, dict):
            rate = result.get("sample_rate")
        return np.asarray(audio, dtype=np.float32).squeeze(), int(rate or 24000)
    raise RuntimeError("MLX-Audio did not yield audio")


def main() -> None:
    request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    model = load_model(request["model_id"])
    generate = model.generate
    common = {
        "text": request["text"],
        "language": request.get("language"),
        "lang_code": request.get("language"),
        "instruct": request.get("instruction"),
        "instruction": request.get("instruction"),
    }
    if request.get("mode") == "clone":
        common.update({
            "ref_audio": request.get("reference_audio"),
            "reference_audio": request.get("reference_audio"),
            "ref_text": request.get("reference_text"),
            "reference_text": request.get("reference_text"),
        })
    else:
        common["voice"] = request.get("voice")
        common["speaker"] = request.get("voice")

    kwargs = accepted_kwargs(generate, common)
    if "text" in inspect.signature(generate).parameters:
        results = generate(**kwargs)
    else:
        text = kwargs.pop("text")
        results = generate(text, **kwargs)
    audio, sample_rate = first_audio(results)
    target = Path(request["output"])
    target.parent.mkdir(parents=True, exist_ok=True)
    sf.write(target, audio, sample_rate)
    print(json.dumps({"ok": True, "output": str(target), "sample_rate": sample_rate,
                      "samples": int(audio.size), "duration": float(audio.size / sample_rate)}))


if __name__ == "__main__":
    main()

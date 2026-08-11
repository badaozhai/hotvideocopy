#!/usr/bin/env python3
"""Launch ACE-Step API without requiring its unused bundled 1.7B LM."""

from __future__ import annotations

import os

import uvicorn

from acestep import model_downloader


# Upstream includes the 1.7B LM in its mandatory "main model" check even when
# ACESTEP_INIT_LLM=false. DiT-only generation needs only these three assets.
model_downloader.MAIN_MODEL_COMPONENTS[:] = [
    "acestep-v15-turbo",
    "vae",
    "Qwen3-Embedding-0.6B",
]

from acestep.api_server import app  # noqa: E402


if __name__ == "__main__":
    uvicorn.run(
        app,
        host=os.environ.get("ACESTEP_API_HOST", "127.0.0.1"),
        port=int(os.environ.get("ACESTEP_API_PORT", "8001")),
        reload=False,
        workers=1,
    )

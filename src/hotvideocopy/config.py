"""运行时配置：全部从环境变量读，无配置文件。

网关统一走自建 CLIProxyAPI；xAI 兼容 OpenAI 协议，所以 base_url 可以是同一个，
也可以给视频通道单独指一个（HVC_VIDEO_BASE_URL）。

Key 分两把是有原因的（移植自 henduohao 实测）：中转把 /v1/videos/* 挂在
【独立鉴权分组】，主 Key 打过去 403。所以 grok_key 缺省才回退 api_key。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _env(*names: str, default: str = "") -> str:
    for n in names:
        v = os.environ.get(n, "").strip()
        if v:
            return v
    return default


@dataclass(frozen=True)
class Config:
    base_url: str
    video_base_url: str
    api_key: str
    grok_key: str
    workspace: Path
    image_model: str
    video_model: str
    whisper_model: str
    hf_token: str
    img_concurrency: int
    proxy: str

    @classmethod
    def load(cls) -> "Config":
        base = _env("HVC_BASE_URL", "OPENAI_BASE_URL", default="")
        ws = _env("HVC_WORKSPACE", default=str(_REPO_ROOT / "workspace"))
        return cls(
            base_url=base,
            video_base_url=_env("HVC_VIDEO_BASE_URL", default=base),
            api_key=_env("HVC_API_KEY", "OPENAI_API_KEY"),
            grok_key=_env("HVC_GROK_KEY", "XAI_API_KEY"),
            workspace=Path(ws).expanduser().resolve(),
            image_model=_env("HVC_IMAGE_MODEL", default="gpt-image-2"),
            video_model=_env("HVC_VIDEO_MODEL", default="grok-imagine-video-1.5"),
            # 中文短视频 BGM 重、语速快，large-v3 和 medium 的差距肉眼可见；嫌慢再降档
            whisper_model=_env("HVC_WHISPER_MODEL", default="large-v3"),
            hf_token=_env("HVC_HF_TOKEN", "HF_TOKEN", "HUGGINGFACE_TOKEN"),
            # 出图并发闸默认 1（串行）。实测中转对并发极敏感，一次多发就大面积 502。
            img_concurrency=max(1, min(6, int(_env("HVC_IMG_CONCURRENCY", default="1") or 1))),
            proxy=_env("HVC_PROXY", "HTTPS_PROXY", "https_proxy"),
        )


CONFIG = Config.load()

# 后台看到 UA 为空不好路由，显式带上（与 henduohao 一致）
CLIENT_UA = "Codex Desktop/0.142.3 (Mac OS 26.4.1; arm64) unknown (Codex Desktop; 26.623.61825)"

RETRIABLE_STATUS = {429, 500, 502, 503, 504}


def auth_headers(key: str, json_body: bool = True) -> dict[str, str]:
    h = {"User-Agent": CLIENT_UA}
    if json_body:
        h["Content-Type"] = "application/json"
    if key:
        h["Authorization"] = f"Bearer {key}"
    return h


def require(value: str, what: str) -> str:
    if not value:
        raise RuntimeError(f"缺少 {what}——请设置对应环境变量（见 .env.example）")
    return value

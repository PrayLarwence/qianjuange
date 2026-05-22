"""xAI Grok - OpenAI 兼容协议.

GET /v1/models 支持模型列表 (返回 grok 系列).
"""
from __future__ import annotations
from typing import ClassVar

from .openai_compat import OpenAICompatibleProvider


class GrokProvider(OpenAICompatibleProvider):
    name = "grok"
    label = "xAI Grok"
    default_model = "grok-4"
    default_models = [
        "grok-4",
        "grok-4-fast-reasoning",
        "grok-4-fast-non-reasoning",
        "grok-3",
        "grok-3-mini",
        "grok-code-fast-1",
    ]
    default_base_url = "https://api.x.ai/v1"
    env_api_key = "XAI_API_KEY"
    env_model = "XAI_MODEL"
    homepage = "https://console.x.ai"

    list_models_supported: ClassVar[bool] = True

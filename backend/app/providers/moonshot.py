"""Moonshot Kimi - 完全 OpenAI 兼容."""
from __future__ import annotations
from typing import ClassVar

from .openai_compat import OpenAICompatibleProvider


class MoonshotProvider(OpenAICompatibleProvider):
    name = "moonshot"
    label = "Moonshot Kimi"
    default_model = "moonshot-v1-32k"
    default_models = [
        "moonshot-v1-8k",
        "moonshot-v1-32k",
        "moonshot-v1-128k",
        "kimi-k2-0905-preview",
        "kimi-latest",
    ]
    default_base_url = "https://api.moonshot.cn/v1"
    env_api_key = "MOONSHOT_API_KEY"
    env_model = "MOONSHOT_MODEL"
    homepage = "https://platform.moonshot.cn"

    list_models_supported: ClassVar[bool] = True

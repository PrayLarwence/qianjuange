"""302.AI - OpenAI 兼容聚合站, 一个 key 路由 200+ 模型.

GET /v1/models 支持列表查询.
"""
from __future__ import annotations
from typing import ClassVar

from .openai_compat import OpenAICompatibleProvider


class AI302Provider(OpenAICompatibleProvider):
    name = "ai302"
    label = "302.AI"
    default_model = "gpt-4o-mini"
    default_models = [
        "gpt-4o",
        "gpt-4o-mini",
        "claude-sonnet-4-5",
        "claude-opus-4-1",
        "deepseek-chat",
        "deepseek-reasoner",
        "gemini-2.5-pro",
        "qwen3-max",
    ]
    default_base_url = "https://api.302.ai/v1"
    env_api_key = "AI302_API_KEY"
    env_model = "AI302_MODEL"
    homepage = "https://302.ai"

    list_models_supported: ClassVar[bool] = True

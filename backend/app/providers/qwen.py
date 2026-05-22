"""通义千问 (DashScope) - OpenAI 兼容模式.

走 https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions.
注意: DashScope 原生协议在 /api/v1, OpenAI 兼容模式在 /compatible-mode/v1.
"""
from __future__ import annotations

from .openai_compat import OpenAICompatibleProvider


class QwenProvider(OpenAICompatibleProvider):
    name = "qwen"
    label = "通义千问"
    default_model = "qwen-plus"
    default_models = [
        "qwen-max",
        "qwen-plus",
        "qwen-turbo",
        "qwen-long",
        "qwen3-max",
        "qwen3-coder-plus",
    ]
    default_base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    env_api_key = "DASHSCOPE_API_KEY"
    env_model = "QWEN_MODEL"
    homepage = "https://dashscope.console.aliyun.com"

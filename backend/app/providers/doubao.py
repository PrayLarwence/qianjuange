"""豆包 / 火山引擎方舟 (Volcengine Ark) - OpenAI 兼容协议.

注意: 豆包的 model 字段填的是 endpoint_id (ep-xxx) 而不是模型名;
也支持直接填模型短名 (doubao-pro-256k 等) 走"模型直连推理".
"""
from __future__ import annotations

from .openai_compat import OpenAICompatibleProvider


class DoubaoProvider(OpenAICompatibleProvider):
    name = "doubao"
    label = "豆包 (火山方舟)"
    default_model = "doubao-seed-1-6-250615"
    default_models = [
        "doubao-seed-1-6-250615",
        "doubao-seed-1-6-flash-250615",
        "doubao-seed-1-6-thinking-250615",
        "doubao-1-5-pro-256k-250115",
        "doubao-1-5-lite-32k-250115",
    ]
    default_base_url = "https://ark.cn-beijing.volces.com/api/v3"
    env_api_key = "ARK_API_KEY"
    env_model = "DOUBAO_MODEL"
    homepage = "https://console.volcengine.com/ark"

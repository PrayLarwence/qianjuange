from __future__ import annotations
from .openai_compat import OpenAICompatibleProvider


class DeepSeekProvider(OpenAICompatibleProvider):
    name = "deepseek"
    label = "DeepSeek"
    default_model = "deepseek-chat"
    default_models = ["deepseek-chat", "deepseek-reasoner"]
    default_base_url = "https://api.deepseek.com/v1"
    env_api_key = "DEEPSEEK_API_KEY"
    env_model = "DEEPSEEK_MODEL"
    homepage = "https://platform.deepseek.com"

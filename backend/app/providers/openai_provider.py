from __future__ import annotations
from .openai_compat import OpenAICompatibleProvider


class OpenAIProvider(OpenAICompatibleProvider):
    name = "openai"
    label = "OpenAI"
    default_model = "gpt-4o-mini"
    default_models = ["gpt-4o-mini", "gpt-4o", "gpt-4-turbo"]
    default_base_url = "https://api.openai.com/v1"
    env_api_key = "OPENAI_API_KEY"
    env_model = "OPENAI_MODEL"
    homepage = "https://platform.openai.com"

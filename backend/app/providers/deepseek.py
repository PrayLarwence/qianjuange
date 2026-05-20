from __future__ import annotations
import os
from .openai_provider import OpenAIProvider


class DeepSeekProvider(OpenAIProvider):
    name = "deepseek"

    def __init__(self, api_key: str | None = None, model: str = "deepseek-chat", base_url: str = "https://api.deepseek.com/v1"):
        super().__init__(
            api_key=api_key or os.getenv("DEEPSEEK_API_KEY", ""),
            model=model,
            base_url=base_url,
        )

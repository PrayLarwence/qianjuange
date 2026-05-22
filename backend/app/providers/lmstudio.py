"""LM Studio - 本地, 完全 OpenAI 兼容.

无需 api_key (本地服务), 默认 ws 端口 1234.
GET /v1/models 返回当前 LM Studio 已加载的模型 (取决于本地用户).
"""
from __future__ import annotations
from typing import Any, ClassVar

from .openai_compat import OpenAICompatibleProvider


class LMStudioProvider(OpenAICompatibleProvider):
    name = "lmstudio"
    label = "LM Studio (本地)"
    default_model = "local-model"
    default_models = ["local-model"]
    default_base_url = "http://localhost:1234/v1"
    env_model = "LMSTUDIO_MODEL"
    env_base_url = "LMSTUDIO_BASE_URL"
    needs_api_key = False
    homepage = "https://lmstudio.ai"

    list_models_supported: ClassVar[bool] = True

    def __init__(self, model: str | None = None, base_url: str | None = None, **_kw: Any):
        # 本地无 api_key, 但仍带个占位符让基类 _build_headers 不抛
        super().__init__(api_key="lm-studio", model=model, base_url=base_url)

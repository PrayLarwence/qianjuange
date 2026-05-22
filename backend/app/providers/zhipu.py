"""智谱 GLM (BigModel.cn) - OpenAI 兼容协议 v4.

GET /v4/models 支持模型列表查询.
"""
from __future__ import annotations
from typing import ClassVar

from .openai_compat import OpenAICompatibleProvider


class ZhipuProvider(OpenAICompatibleProvider):
    name = "zhipu"
    label = "智谱 GLM"
    default_model = "glm-4-plus"
    default_models = [
        "glm-4-plus",
        "glm-4-air",
        "glm-4-flash",
        "glm-4.5",
        "glm-4.5-air",
        "glm-4v-plus",
    ]
    default_base_url = "https://open.bigmodel.cn/api/paas/v4"
    env_api_key = "ZHIPU_API_KEY"
    env_model = "ZHIPU_MODEL"
    homepage = "https://open.bigmodel.cn"

    list_models_supported: ClassVar[bool] = True

"""SiliconFlow (硅基流动) - OpenAI 兼容协议.

聚合了 DeepSeek / Qwen / GLM / Kimi / Llama 等开源模型, 价格便宜.
GET /v1/models 支持模型列表.
"""
from __future__ import annotations
from typing import ClassVar

from .openai_compat import OpenAICompatibleProvider


class SiliconFlowProvider(OpenAICompatibleProvider):
    name = "siliconflow"
    label = "SiliconFlow"
    default_model = "deepseek-ai/DeepSeek-V3"
    default_models = [
        "deepseek-ai/DeepSeek-V3",
        "deepseek-ai/DeepSeek-R1",
        "Qwen/Qwen3-235B-A22B-Instruct-2507",
        "Qwen/Qwen3-Coder-480B-A35B-Instruct",
        "moonshotai/Kimi-K2-Instruct",
        "zai-org/GLM-4.5",
    ]
    default_base_url = "https://api.siliconflow.cn/v1"
    env_api_key = "SILICONFLOW_API_KEY"
    env_model = "SILICONFLOW_MODEL"
    homepage = "https://cloud.siliconflow.cn"

    list_models_supported: ClassVar[bool] = True

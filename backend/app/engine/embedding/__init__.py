"""Embedding provider 抽象。

阶段 0 只定形状，三个后端实现都先 raise NotImplementedError，B2 阶段填实。
后续所有用到 embedding 的代码（B2 RAG 检索 / B4 风格漂移检测）都走
get_provider() —— 切换 provider 不动业务代码。
"""
from .base import EmbeddingProvider, NullProvider, get_provider, register_provider
from .local_bge import LocalBGEProvider
from .zhipu import ZhipuProvider
from .siliconflow import SiliconFlowProvider

# 默认注册三个 stub。实装后这些类直接换实现，注册表不变。
register_provider("local_bge", LocalBGEProvider())
register_provider("zhipu", ZhipuProvider())
register_provider("siliconflow", SiliconFlowProvider())

AVAILABLE_PROVIDERS = ["local_bge", "zhipu", "siliconflow"]

__all__ = [
    "EmbeddingProvider", "NullProvider",
    "LocalBGEProvider", "ZhipuProvider", "SiliconFlowProvider",
    "get_provider", "register_provider", "AVAILABLE_PROVIDERS",
]

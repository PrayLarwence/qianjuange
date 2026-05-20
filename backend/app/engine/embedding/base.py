from __future__ import annotations
from typing import Protocol, Sequence, Dict, Any, List


class EmbeddingProvider(Protocol):
    """Embedding 后端协议。所有实现必须无副作用、可重入。"""

    name: str
    model: str
    dim: int

    def embed(self, texts: Sequence[str]) -> List[List[float]]:
        """返回 len(texts) 个向量，每个长度 == self.dim。空列表返回空列表。"""
        ...

    def health_check(self) -> Dict[str, Any]:
        """探活。返回 {ok: bool, detail: str}。失败时 ok=False，detail 含原因。"""
        ...


class NullProvider:
    """占位实现。用于 World.embedding_provider 为空 / 未配置时。

    embed 直接抛 RuntimeError 防止被悄悄使用——RAG 入口在调用前应先检查。
    """
    name = "null"
    model = ""
    dim = 0

    def embed(self, texts: Sequence[str]) -> List[List[float]]:
        if not texts:
            return []
        raise RuntimeError("embedding provider 未配置（World.embedding_provider 为空）")

    def health_check(self) -> Dict[str, Any]:
        return {"ok": False, "detail": "no provider configured"}


_REGISTRY: Dict[str, EmbeddingProvider] = {}


def register_provider(name: str, provider: EmbeddingProvider) -> None:
    _REGISTRY[name] = provider


def get_provider(name: str | None) -> EmbeddingProvider:
    """按名称取 provider；未注册或 None 返回 NullProvider。"""
    if not name:
        return NullProvider()
    return _REGISTRY.get(name, NullProvider())

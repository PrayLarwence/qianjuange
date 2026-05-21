"""MetricsProvider：包装 LLMProvider，每次 chat() 调用自动记录 token / 耗时。"""
from __future__ import annotations
import time
import logging
from .base import LLMProvider, LLMResponse, Message, ToolSpec

log = logging.getLogger(__name__)


class MetricsProvider:
    """包装 LLMProvider，记录每次调用到 llm_call_metrics 表。"""

    def __init__(self, inner: LLMProvider, kind: str = "", world_id: str = ""):
        self._inner = inner
        self._kind = kind
        self._world_id = world_id

    @property
    def name(self) -> str:
        return self._inner.name if hasattr(self._inner, 'name') else "unknown"

    def chat(
        self, system: str, messages: list[Message],
        tools: list | None = None,
        max_tokens: int = 2048, temperature: float = 0.7,
        timeout: float = 120.0,
    ) -> LLMResponse:
        t0 = time.monotonic()
        model = getattr(self._inner, 'model', 'unknown')
        try:
            resp = self._inner.chat(
                system=system, messages=messages,
                tools=tools, max_tokens=max_tokens,
                temperature=temperature, timeout=timeout,
            )
            latency_ms = int((time.monotonic() - t0) * 1000)
            usage = resp.usage or {}
            tokens_in = usage.get("input_tokens") or usage.get("prompt_tokens") or 0
            tokens_out = usage.get("output_tokens") or usage.get("completion_tokens") or 0

            from ..engine.core.metrics import record_llm_call
            record_llm_call(
                provider=self.name, model=model, kind=self._kind,
                world_id=self._world_id,
                tokens_in=tokens_in, tokens_out=tokens_out,
                latency_ms=latency_ms, status="ok",
            )
            return resp
        except Exception as e:
            latency_ms = int((time.monotonic() - t0) * 1000)
            from ..engine.core.metrics import record_llm_call
            record_llm_call(
                provider=self.name, model=model, kind=self._kind,
                world_id=self._world_id,
                latency_ms=latency_ms, status="error",
                error=str(e)[:200],
            )
            raise

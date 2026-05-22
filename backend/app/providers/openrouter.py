"""OpenRouter: 一个 key 路由到 200+ 模型 (Claude / GPT / Gemini / 开源).

完全兼容 OpenAI Chat Completions 协议. 额外加两个 header (HTTP-Referer / X-Title),
让请求在 OpenRouter 控制台和公开排行榜里能识别来源.

支持动态模型列表: GET /api/v1/models 返回 200+ 条 {id, name, pricing, context_length...}.
"""
from __future__ import annotations
from typing import ClassVar

from .openai_compat import OpenAICompatibleProvider

# 默认推荐 6 个跨家模型, 仅作初始下拉建议; 真实可用列表前端按需 fetch
_DEFAULT_PICKS = [
    "anthropic/claude-opus-4",
    "anthropic/claude-sonnet-4",
    "openai/gpt-4o",
    "openai/gpt-4o-mini",
    "google/gemini-2.5-pro",
    "deepseek/deepseek-chat",
    "moonshotai/kimi-k2",
    "x-ai/grok-2",
]


class OpenRouterProvider(OpenAICompatibleProvider):
    name = "openrouter"
    label = "OpenRouter"
    default_model = "openai/gpt-4o-mini"
    default_models = _DEFAULT_PICKS
    default_base_url = "https://openrouter.ai/api/v1"
    env_api_key = "OPENROUTER_API_KEY"
    env_model = "OPENROUTER_MODEL"
    homepage = "https://openrouter.ai"

    # 动态拉模型列表
    list_models_supported: ClassVar[bool] = True

    # 排行榜署名 (OpenRouter 推荐传, 不传也能用)
    referer: ClassVar[str] = "https://github.com/burning-sun-prayers-for-rain/narrative-sandbox"
    title: ClassVar[str] = "Narrative Sandbox"

    def _build_headers(self) -> dict[str, str]:
        h = super()._build_headers()
        h["HTTP-Referer"] = self.referer
        h["X-Title"] = self.title
        return h

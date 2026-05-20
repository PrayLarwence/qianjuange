from __future__ import annotations
from .base import LLMProvider, LLMResponse, Message, ToolCall, ToolSpec
from .claude import ClaudeProvider
from .openai_provider import OpenAIProvider
from .deepseek import DeepSeekProvider
from .ollama import OllamaProvider
from .config import load_config, save_config, mask, get_provider_config


PROVIDER_CLASSES = {
    "claude": ClaudeProvider,
    "openai": OpenAIProvider,
    "deepseek": DeepSeekProvider,
    "ollama": OllamaProvider,
}


def get_provider(name: str | None = None) -> LLMProvider:
    cfg = load_config()
    name = (name or cfg.get("active") or "claude").lower()
    cls = PROVIDER_CLASSES.get(name)
    if not cls:
        raise ValueError(f"unknown provider: {name}")
    p = cfg["providers"].get(name, {})
    kwargs = {}
    if "api_key" in p and p.get("api_key"):
        kwargs["api_key"] = p["api_key"]
    if p.get("model"):
        kwargs["model"] = p["model"]
    if p.get("base_url"):
        kwargs["base_url"] = p["base_url"]
    if name == "ollama":
        kwargs.pop("api_key", None)
    return cls(**kwargs)


__all__ = [
    "LLMProvider", "LLMResponse", "Message", "ToolCall", "ToolSpec",
    "ClaudeProvider", "OpenAIProvider", "DeepSeekProvider", "OllamaProvider",
    "get_provider", "PROVIDER_CLASSES",
    "load_config", "save_config", "mask", "get_provider_config",
]

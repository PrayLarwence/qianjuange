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


def get_provider_for_role(world, role: str) -> LLMProvider:
    """按角色取 LLM provider。role ∈ {'director','author','editor','reader'}。

    World 上的 {role}_model_override 字段格式：
      - 空字符串       → 用主 provider（默认配置）
      - 'model_name'   → 主 provider 但替换 model 字段
      - 'provider:model' → 切到指定 provider + model

    阶段 0 所有 role 默认空，全部走主 provider（DeepSeek V4 当前配置）。
    """
    override = ""
    if world is not None:
        override = (getattr(world, f"{role}_model_override", "") or "").strip()
    if not override:
        return get_provider()
    if ":" in override:
        provider_name, model_name = override.split(":", 1)
        provider_name = provider_name.strip().lower()
        model_name = model_name.strip()
    else:
        provider_name = (load_config().get("active") or "claude").lower()
        model_name = override
    cls = PROVIDER_CLASSES.get(provider_name)
    if not cls:
        # 未知 provider 名 → 回落主 provider，避免角色级配置错误把整个推演弄崩
        return get_provider()
    cfg = load_config()
    p = cfg["providers"].get(provider_name, {})
    kwargs = {"model": model_name} if model_name else {}
    if p.get("api_key"):
        kwargs["api_key"] = p["api_key"]
    if p.get("base_url"):
        kwargs["base_url"] = p["base_url"]
    if provider_name == "ollama":
        kwargs.pop("api_key", None)
    return cls(**kwargs)


__all__ = [
    "LLMProvider", "LLMResponse", "Message", "ToolCall", "ToolSpec",
    "ClaudeProvider", "OpenAIProvider", "DeepSeekProvider", "OllamaProvider",
    "get_provider", "get_provider_for_role", "PROVIDER_CLASSES",
    "load_config", "save_config", "mask", "get_provider_config",
]

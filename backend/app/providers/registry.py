"""Provider 注册表。子类通过 base.BaseProvider.__init_subclass__ 自动登记。

派生 4 个集合：
- PROVIDER_CLASSES: name → class
- PROVIDER_META:    name → 前端元信息
- DEFAULTS:         config.json 默认结构
- ENV_KEYS:         环境变量名映射
"""
from __future__ import annotations
from typing import Any

PROVIDER_CLASSES: dict[str, type] = {}


def register(cls: type) -> None:
    name = getattr(cls, "name", "")
    if not name:
        return
    PROVIDER_CLASSES[name] = cls


def provider_meta() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for name, cls in PROVIDER_CLASSES.items():
        out[name] = {
            "label": cls.label or name,
            "needs_api_key": cls.needs_api_key,
            "supports_native_tools": cls.supports_native_tools,
            "supports_listing": getattr(cls, "list_models_supported", False),
            "default_models": list(cls.default_models),
            "homepage": cls.homepage,
        }
    return out


def provider_defaults() -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for name, cls in PROVIDER_CLASSES.items():
        out[name] = {
            "api_key": "",
            "model": cls.default_model,
            "base_url": cls.default_base_url,
        }
    return out


def env_keys() -> dict[str, tuple[str | None, str | None, str | None]]:
    out: dict[str, tuple[str | None, str | None, str | None]] = {}
    for name, cls in PROVIDER_CLASSES.items():
        out[name] = (cls.env_api_key, cls.env_model, cls.env_base_url)
    return out


def import_all_providers() -> None:
    """触发所有 provider 模块导入，让 __init_subclass__ 注册。

    config.py / __init__.py 调用前先 import 这个，确保全员就位。
    """
    from . import claude, openai_compat, openai_provider, deepseek, ollama, openrouter  # noqa: F401

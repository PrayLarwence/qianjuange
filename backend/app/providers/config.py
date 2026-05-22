from __future__ import annotations
import json
import os
from typing import Any
from threading import RLock

from . import registry
from .secret import decrypt as _decrypt, encrypt as _encrypt
from ..paths import LLM_CONFIG_PATH as CONFIG_PATH, DATA_DIR  # noqa: F401  re-export 给老调用方

# 触发 provider 模块导入 → __init_subclass__ 注册
registry.import_all_providers()

_lock = RLock()


def _defaults() -> dict[str, Any]:
    """每次调用现算，保证新注册的 provider 立刻生效。"""
    return {
        "active": "claude" if "claude" in registry.PROVIDER_CLASSES else next(iter(registry.PROVIDER_CLASSES), ""),
        "providers": registry.provider_defaults(),
    }


def _merge_env(cfg: dict[str, Any]) -> dict[str, Any]:
    for name, (key_env, model_env, url_env) in registry.env_keys().items():
        defaults = registry.provider_defaults().get(name, {})
        p = cfg["providers"].setdefault(name, dict(defaults))
        if not p.get("api_key") and key_env and os.getenv(key_env):
            p["api_key"] = os.getenv(key_env, "")
        if model_env and os.getenv(model_env):
            p["model"] = os.getenv(model_env, p.get("model", ""))
        if url_env and os.getenv(url_env):
            p["base_url"] = os.getenv(url_env, p.get("base_url", ""))
    if env_active := os.getenv("LLM_PROVIDER"):
        if not CONFIG_PATH.exists():
            cfg["active"] = env_active
    return cfg


def load_config() -> dict[str, Any]:
    with _lock:
        defaults = _defaults()
        if CONFIG_PATH.exists():
            try:
                cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                cfg = json.loads(json.dumps(defaults))
        else:
            cfg = json.loads(json.dumps(defaults))
        cfg.setdefault("active", defaults["active"])
        cfg.setdefault("providers", {})
        # 给所有已注册 provider 兜底字段
        for k, v in defaults["providers"].items():
            cfg["providers"].setdefault(k, dict(v))
            for fld, default in v.items():
                cfg["providers"][k].setdefault(fld, default)
        # 透明解密 api_key (旧 plain 文件原样穿透; 已迁移密文解出明文)
        for p in cfg["providers"].values():
            raw = p.get("api_key", "") or ""
            if raw:
                p["api_key"] = _decrypt(raw)
        return _merge_env(cfg)


def save_config(updates: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        existing = load_config()
        if "active" in updates and updates["active"] in existing["providers"]:
            existing["active"] = updates["active"]
        for name, patch in (updates.get("providers") or {}).items():
            if name not in existing["providers"]:
                continue
            target = existing["providers"][name]
            for key, value in patch.items():
                if key == "api_key":
                    if value in (None, "", "***"):
                        continue
                    target["api_key"] = value
                elif key in ("model", "base_url"):
                    if value is None:
                        continue
                    target[key] = value
        # 写盘前把所有非空 api_key 加密 (深拷贝, 避免污染内存里的明文)
        on_disk = json.loads(json.dumps(existing))
        for p in on_disk["providers"].values():
            plain = p.get("api_key", "") or ""
            if plain:
                p["api_key"] = _encrypt(plain)
        CONFIG_PATH.write_text(json.dumps(on_disk, ensure_ascii=False, indent=2), encoding="utf-8")
        return existing


def mask(cfg: dict[str, Any]) -> dict[str, Any]:
    out = json.loads(json.dumps(cfg))
    for p in out["providers"].values():
        key = p.get("api_key", "") or ""
        if key:
            p["api_key_preview"] = (key[:4] + "…" + key[-4:]) if len(key) > 12 else "***"
            p["has_key"] = True
        else:
            p["api_key_preview"] = ""
            p["has_key"] = False
        p.pop("api_key", None)
    return out


def get_provider_config(name: str) -> dict[str, Any]:
    cfg = load_config()
    return cfg["providers"].get(name, {})

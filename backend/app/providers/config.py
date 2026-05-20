from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Any
from threading import RLock

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_PATH = DATA_DIR / "llm_config.json"

_lock = RLock()

DEFAULTS: dict[str, Any] = {
    "active": "claude",
    "providers": {
        "claude": {
            "api_key": "",
            "model": "claude-opus-4-7",
            "base_url": "https://api.anthropic.com",
        },
        "openai": {
            "api_key": "",
            "model": "gpt-4o-mini",
            "base_url": "https://api.openai.com/v1",
        },
        "deepseek": {
            "api_key": "",
            "model": "deepseek-chat",
            "base_url": "https://api.deepseek.com/v1",
        },
        "ollama": {
            "api_key": "",
            "model": "llama3.1",
            "base_url": "http://localhost:11434",
        },
    },
}

ENV_KEYS = {
    "claude": ("ANTHROPIC_API_KEY", "CLAUDE_MODEL", None),
    "openai": ("OPENAI_API_KEY", "OPENAI_MODEL", None),
    "deepseek": ("DEEPSEEK_API_KEY", "DEEPSEEK_MODEL", None),
    "ollama": (None, "OLLAMA_MODEL", "OLLAMA_BASE_URL"),
}


def _merge_env(cfg: dict[str, Any]) -> dict[str, Any]:
    for name, (key_env, model_env, url_env) in ENV_KEYS.items():
        p = cfg["providers"].setdefault(name, dict(DEFAULTS["providers"][name]))
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
        if CONFIG_PATH.exists():
            try:
                cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                cfg = json.loads(json.dumps(DEFAULTS))
        else:
            cfg = json.loads(json.dumps(DEFAULTS))
        cfg.setdefault("active", DEFAULTS["active"])
        cfg.setdefault("providers", {})
        for k, v in DEFAULTS["providers"].items():
            cfg["providers"].setdefault(k, dict(v))
            for field, default in v.items():
                cfg["providers"][k].setdefault(field, default)
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
        CONFIG_PATH.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
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

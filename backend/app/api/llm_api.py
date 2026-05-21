"""LLM provider 配置 / 度量 API。

5 端点：
- GET  /llm_config
- POST /llm_config
- POST /llm_config/test
- GET  /providers
- GET  /metrics
"""
from __future__ import annotations
import logging
from typing import Any
import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..providers import (
    get_provider, load_config, save_config, mask, PROVIDER_CLASSES, Message,
)

log = logging.getLogger(__name__)
router = APIRouter()


PROVIDER_META = {
    "claude": {
        "label": "Claude (Anthropic)",
        "needs_api_key": True,
        "default_models": ["claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"],
        "homepage": "https://console.anthropic.com",
    },
    "openai": {
        "label": "OpenAI",
        "needs_api_key": True,
        "default_models": ["gpt-4o-mini", "gpt-4o", "gpt-4-turbo"],
        "homepage": "https://platform.openai.com",
    },
    "deepseek": {
        "label": "DeepSeek",
        "needs_api_key": True,
        "default_models": ["deepseek-chat", "deepseek-reasoner"],
        "homepage": "https://platform.deepseek.com",
    },
    "ollama": {
        "label": "Ollama (本地)",
        "needs_api_key": False,
        "default_models": ["llama3.1", "qwen2.5", "mistral", "deepseek-r1"],
        "homepage": "https://ollama.com",
    },
}


@router.get("/llm_config")
def get_llm_config():
    cfg = load_config()
    return {"config": mask(cfg), "meta": PROVIDER_META}


class LLMConfigUpdate(BaseModel):
    active: str | None = None
    providers: dict[str, dict[str, Any]] | None = None


@router.post("/llm_config")
def update_llm_config(payload: LLMConfigUpdate):
    updates = {}
    if payload.active:
        if payload.active not in PROVIDER_CLASSES:
            raise HTTPException(400, f"unknown provider: {payload.active}")
        updates["active"] = payload.active
    if payload.providers:
        updates["providers"] = payload.providers
    cfg = save_config(updates)
    return {"ok": True, "config": mask(cfg)}


class LLMTestRequest(BaseModel):
    provider: str


@router.post("/llm_config/test")
def test_llm_config(payload: LLMTestRequest):
    if payload.provider not in PROVIDER_CLASSES:
        raise HTTPException(400, f"unknown provider: {payload.provider}")
    import time
    t0 = time.time()
    try:
        provider = get_provider(payload.provider)
        cfg = load_config()["providers"].get(payload.provider, {})
        if payload.provider != "ollama" and not cfg.get("api_key"):
            return {"ok": False, "error": "未配置 API Key（请先粘贴 Key 再点测试）", "elapsed": 0}
        resp = provider.chat(
            system="You are a connectivity test endpoint. Reply with exactly: OK",
            messages=[Message(role="user", content="ping")],
            tools=[],
            max_tokens=16,
            temperature=0.0,
            timeout=60.0,
        )
        return {
            "ok": True,
            "reply": (resp.text or "(空回复)").strip()[:200],
            "usage": resp.usage,
            "elapsed": round(time.time() - t0, 2),
            "model": getattr(provider, "model", ""),
            "base_url": getattr(provider, "base_url", ""),
        }
    except httpx.ConnectTimeout:
        return {"ok": False, "error": f"连接超时（无法在 60 秒内建立到 API 的连接，可能被网络阻断）", "elapsed": round(time.time() - t0, 2)}
    except httpx.ReadTimeout:
        return {"ok": False, "error": f"读取超时（已建立连接但 60 秒内未收到响应，API 可能拥堵）", "elapsed": round(time.time() - t0, 2)}
    except httpx.HTTPStatusError as e:
        body = ""
        try:
            body = e.response.text[:300]
        except Exception:
            pass
        return {"ok": False, "error": f"HTTP {e.response.status_code}: {body}", "elapsed": round(time.time() - t0, 2)}
    except httpx.ConnectError as e:
        return {"ok": False, "error": f"连接失败: {e}（DNS 解析失败或网络不通）", "elapsed": round(time.time() - t0, 2)}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:300]}", "elapsed": round(time.time() - t0, 2)}


@router.get("/providers")
def list_providers():
    cfg = load_config()
    return {
        "current": cfg["active"],
        "available": list(PROVIDER_CLASSES.keys()),
        "models": {k: v.get("model") for k, v in cfg["providers"].items()},
    }


# ─── 度量查询 ──────────────────────────────────────────────────

@router.get("/metrics")
def get_metrics(
    hours: int = 24,
    provider: str | None = None,
    kind: str | None = None,
):
    from ..models import get_db, SessionLocal, LlmCallMetric
    from ..engine.core.metrics import query_metrics
    db = SessionLocal()
    try:
        return query_metrics(db, hours=hours, provider=provider, kind=kind)
    finally:
        db.close()

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
from ..providers import registry

log = logging.getLogger(__name__)
router = APIRouter()


@router.get("/llm_config")
def get_llm_config():
    cfg = load_config()
    return {"config": mask(cfg), "meta": registry.provider_meta()}


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


@router.get("/llm_config/models")
def list_provider_models(provider: str):
    """动态拉某个 provider 的可用模型列表（OpenRouter / OpenAI 等支持）。

    返回 [{id, name, context_length, pricing}] 或 [] (provider 不支持时).
    pricing/context_length 由各家自行决定字段, 前端按需读.
    """
    if provider not in PROVIDER_CLASSES:
        raise HTTPException(400, f"unknown provider: {provider}")
    cls = PROVIDER_CLASSES[provider]
    if not getattr(cls, "list_models_supported", False):
        return {"ok": False, "error": f"{provider} 不支持动态模型列表", "models": []}
    cfg = load_config()
    p = cfg["providers"].get(provider, {})
    kwargs: dict[str, Any] = {}
    if p.get("api_key"):
        kwargs["api_key"] = p["api_key"]
    if p.get("base_url"):
        kwargs["base_url"] = p["base_url"]
    if not getattr(cls, "needs_api_key", True):
        kwargs.pop("api_key", None)
    try:
        instance = cls(**kwargs)
        raw = instance.list_models(timeout=30.0)
        # 标准化关键字段（OpenRouter 给 id/name/context_length/pricing,
        # OpenAI 只给 id/created/owned_by, 字段缺失给 None）
        models = []
        for m in raw:
            if not isinstance(m, dict):
                continue
            models.append({
                "id": m.get("id", ""),
                "name": m.get("name") or m.get("id", ""),
                "context_length": m.get("context_length"),
                "pricing": m.get("pricing"),  # OpenRouter 有 prompt/completion 单价
            })
        models.sort(key=lambda x: x["id"])
        return {"ok": True, "models": models, "count": len(models)}
    except httpx.HTTPStatusError as e:
        body = ""
        try:
            body = e.response.text[:300]
        except Exception:
            pass
        return {"ok": False, "error": f"HTTP {e.response.status_code}: {body}", "models": []}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:300]}", "models": []}


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

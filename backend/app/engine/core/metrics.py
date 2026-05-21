"""LLM 调用度量记录。每次 chat() 自动写入一张独立 SQLite 表。

用法：
  from .metrics import record_llm_call
  record_llm_call(provider="deepseek", model="deepseek-chat", kind="step",
                  tokens_in=1500, tokens_out=300, latency_ms=1200)
"""
from __future__ import annotations
import time
import uuid
import logging
from threading import Lock
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from ..models import LlmCallMetric

log = logging.getLogger(__name__)
_lock = Lock()


def record_llm_call(
    provider: str,
    model: str,
    kind: str = "",
    *,
    world_id: str = "",
    tokens_in: int = 0,
    tokens_out: int = 0,
    latency_ms: int = 0,
    status: str = "ok",
    error: str = "",
) -> None:
    try:
        from ..models import SessionLocal  # lazy import to avoid circular
        metric = LlmCallMetric(
            id=f"llm_{uuid.uuid4().hex[:10]}",
            provider=provider,
            model=model,
            kind=kind,
            world_id=world_id,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency_ms,
            status=status,
            error=error,
            created_at=datetime.utcnow(),
        )
        db: Session = SessionLocal()
        try:
            db.add(metric)
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()
    except Exception:
        pass  # metrics 永远不影响主流程


def query_metrics(
    db: Session,
    hours: int = 24,
    provider: Optional[str] = None,
    kind: Optional[str] = None,
) -> dict:
    """聚合查询：返回时间段内的汇总统计。"""
    from datetime import timedelta
    cutoff = datetime.utcnow() - timedelta(hours=hours)

    q = db.query(LlmCallMetric).filter(LlmCallMetric.created_at >= cutoff)
    if provider:
        q = q.filter(LlmCallMetric.provider == provider)
    if kind:
        q = q.filter(LlmCallMetric.kind == kind)

    rows = q.order_by(LlmCallMetric.created_at.desc()).limit(200).all()

    total_tokens_in = sum(r.tokens_in or 0 for r in rows)
    total_tokens_out = sum(r.tokens_out or 0 for r in rows)
    total_calls = len(rows)
    errors = sum(1 for r in rows if r.status == "error")
    avg_latency = sum(r.latency_ms or 0 for r in rows) / max(total_calls, 1)

    by_provider: dict[str, dict] = {}
    for r in rows:
        p = r.provider or "unknown"
        if p not in by_provider:
            by_provider[p] = {"calls": 0, "tokens_in": 0, "tokens_out": 0, "errors": 0}
        d = by_provider[p]
        d["calls"] += 1
        d["tokens_in"] += r.tokens_in or 0
        d["tokens_out"] += r.tokens_out or 0
        if r.status == "error":
            d["errors"] += 1

    recent = [
        {
            "id": r.id, "provider": r.provider, "model": r.model,
            "kind": r.kind, "tokens_in": r.tokens_in, "tokens_out": r.tokens_out,
            "latency_ms": r.latency_ms, "status": r.status,
            "error": r.error, "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows[:50]
    ]

    return {
        "summary": {
            "total_calls": total_calls,
            "total_tokens_in": total_tokens_in,
            "total_tokens_out": total_tokens_out,
            "errors": errors,
            "avg_latency_ms": round(avg_latency, 1),
        },
        "by_provider": by_provider,
        "recent": recent,
    }

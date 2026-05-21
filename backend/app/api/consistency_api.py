"""一致性扫描 / Issue / Patch / scene_continuity 相关 API。

11 个端点：
- POST /worlds/{id}/scan_consistency
- GET  /worlds/{id}/issues
- PATCH /issues/{id}
- DELETE /issues/{id}
- GET  /issues/{id}/patches
- POST /issues/{id}/suggest_patch
- POST /worlds/{id}/issues/suggest_all_patches
- POST /issue_patches/{id}/apply
- POST /issue_patches/{id}/reject
- POST /issue_patches/{id}/undo
- GET  /issue_patches/{id}/preview
- POST /worlds/{id}/scene_continuity/scan
"""
from __future__ import annotations
import logging
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..models import get_db, World, ConsistencyIssue, ScanRun
from ..engine.consistency import run_scan as _run_scan, CATEGORY_LABELS as _CAT_LABELS

log = logging.getLogger(__name__)
router = APIRouter()


# ─── 序列化 helper ──────────────────────────────────────────────

def _issue_dict(i: ConsistencyIssue) -> dict:
    return {
        "id": i.id, "world_id": i.world_id, "branch_id": i.branch_id,
        "category": i.category, "category_label": _CAT_LABELS.get(i.category, "其它"),
        "severity": i.severity, "title": i.title,
        "description": i.description, "suggestion": i.suggestion,
        "entity_ids": i.entity_ids or [],
        "tick_start": i.tick_start, "tick_end": i.tick_end,
        "status": i.status, "scan_id": i.scan_id,
        "created_at": i.created_at.isoformat() if i.created_at else None,
        "resolved_at": i.resolved_at.isoformat() if i.resolved_at else None,
    }


def _scan_dict(s: ScanRun) -> dict:
    return {
        "id": s.id, "world_id": s.world_id, "scope": s.scope,
        "tick_from": s.tick_from, "tick_to": s.tick_to,
        "issue_count": s.issue_count, "status": s.status, "error": s.error,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }


def _patch_dict(p) -> dict:
    return {
        "id": p.id, "issue_id": p.issue_id,
        "target_kind": p.target_kind, "target_id": p.target_id,
        "before_excerpt": p.before_excerpt or "",
        "after_text": p.after_text or "",
        "rationale": p.rationale or "",
        "status": p.status,
        "model_used": p.model_used or "",
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "applied_at": p.applied_at.isoformat() if p.applied_at else None,
        "can_undo": p.status == "applied",
    }


# ─── 一致性扫描 ────────────────────────────────────────────────

class ScanRequest(BaseModel):
    scope: str = "recent"
    tick_from: Optional[int] = None
    tick_to: Optional[int] = None
    provider: Optional[str] = None


@router.post("/worlds/{world_id}/scan_consistency")
def scan_consistency(world_id: str, payload: ScanRequest, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    run = _run_scan(
        db, world,
        scope=payload.scope or "recent",
        tick_from=payload.tick_from, tick_to=payload.tick_to,
        provider_key=payload.provider,
    )
    issues = (
        db.query(ConsistencyIssue)
        .filter_by(scan_id=run.id)
        .order_by(ConsistencyIssue.created_at.desc())
        .all()
    )
    return {"scan": _scan_dict(run), "issues": [_issue_dict(i) for i in issues]}


@router.get("/worlds/{world_id}/issues")
def list_issues(
    world_id: str,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    q = db.query(ConsistencyIssue).filter_by(world_id=world_id)
    if status:
        q = q.filter(ConsistencyIssue.status == status)
    issues = q.order_by(ConsistencyIssue.created_at.desc()).limit(200).all()
    runs = (
        db.query(ScanRun).filter_by(world_id=world_id)
        .order_by(ScanRun.created_at.desc()).limit(20).all()
    )
    counts = {
        "open": db.query(ConsistencyIssue).filter_by(world_id=world_id, status="open").count(),
        "ignored": db.query(ConsistencyIssue).filter_by(world_id=world_id, status="ignored").count(),
        "resolved": db.query(ConsistencyIssue).filter_by(world_id=world_id, status="resolved").count(),
    }
    return {
        "issues": [_issue_dict(i) for i in issues],
        "scans": [_scan_dict(s) for s in runs],
        "counts": counts,
    }


class IssueUpdate(BaseModel):
    status: str


@router.patch("/issues/{issue_id}")
def update_issue(issue_id: str, payload: IssueUpdate, db: Session = Depends(get_db)):
    issue = db.query(ConsistencyIssue).filter_by(id=issue_id).first()
    if not issue:
        raise HTTPException(404, "issue not found")
    if payload.status not in ("open", "ignored", "resolved"):
        raise HTTPException(400, "invalid status")
    issue.status = payload.status
    if payload.status in ("ignored", "resolved"):
        issue.resolved_at = datetime.utcnow()
    else:
        issue.resolved_at = None
    db.commit()
    return _issue_dict(issue)


@router.delete("/issues/{issue_id}")
def delete_issue(issue_id: str, db: Session = Depends(get_db)):
    issue = db.query(ConsistencyIssue).filter_by(id=issue_id).first()
    if not issue:
        raise HTTPException(404, "issue not found")
    db.delete(issue)
    db.commit()
    return {"ok": True}


# ─── Editor patch 建议 ─────────────────────────────────────────

class SuggestPatchRequest(BaseModel):
    provider: str | None = None
    max_patches: int = 3


@router.get("/issues/{issue_id}/patches")
def list_issue_patches(issue_id: str, db: Session = Depends(get_db)):
    from ..models import IssuePatch
    issue = db.query(ConsistencyIssue).filter_by(id=issue_id).first()
    if not issue:
        raise HTTPException(404, "issue not found")
    patches = (db.query(IssuePatch).filter_by(issue_id=issue_id)
               .order_by(IssuePatch.created_at.desc()).all())
    return {"issue_id": issue_id, "patches": [_patch_dict(p) for p in patches]}


@router.post("/issues/{issue_id}/suggest_patch")
def suggest_issue_patch(issue_id: str, payload: SuggestPatchRequest, db: Session = Depends(get_db)):
    from ..engine.patch import suggest_patches_for_issue
    issue = db.query(ConsistencyIssue).filter_by(id=issue_id).first()
    if not issue:
        raise HTTPException(404, "issue not found")
    world = db.query(World).filter_by(id=issue.world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    try:
        created = suggest_patches_for_issue(
            db, world, issue,
            provider_key=payload.provider,
            max_patches=payload.max_patches,
        )
    except Exception as e:
        raise HTTPException(500, f"suggest failed: {e}")
    return {"issue_id": issue_id, "created": len(created), "patches": [_patch_dict(p) for p in created]}


class BatchSuggestRequest(BaseModel):
    provider: str | None = None
    max_patches: int = 3
    skip_existing: bool = True
    limit: int = 20


@router.post("/worlds/{world_id}/issues/suggest_all_patches")
def suggest_all_issue_patches(world_id: str, payload: BatchSuggestRequest, db: Session = Depends(get_db)):
    """对当前 world 所有 open issue 批量生成 patch 建议。"""
    from ..models import IssuePatch
    from ..engine.patch import suggest_patches_for_issue

    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")

    open_issues = (
        db.query(ConsistencyIssue)
        .filter_by(world_id=world_id, status="open")
        .order_by(ConsistencyIssue.created_at.desc())
        .all()
    )

    if payload.skip_existing:
        existing_iids = {
            row.issue_id for row in
            db.query(IssuePatch.issue_id).filter(
                IssuePatch.issue_id.in_([i.id for i in open_issues])
            ).distinct().all()
        }
        candidates = [i for i in open_issues if i.id not in existing_iids]
    else:
        candidates = list(open_issues)

    cap = max(1, min(int(payload.limit or 20), 50))
    candidates = candidates[:cap]

    results = []
    total_created = 0
    for iss in candidates:
        try:
            created = suggest_patches_for_issue(
                db, world, iss,
                provider_key=payload.provider,
                max_patches=payload.max_patches,
            )
            results.append({
                "issue_id": iss.id,
                "title": iss.title,
                "created": len(created),
                "ok": True,
            })
            total_created += len(created)
        except Exception as e:
            results.append({
                "issue_id": iss.id,
                "title": iss.title,
                "created": 0,
                "ok": False,
                "error": str(e)[:200],
            })

    return {
        "world_id": world_id,
        "processed": len(candidates),
        "skipped_existing": len(open_issues) - len(candidates) if payload.skip_existing else 0,
        "total_open": len(open_issues),
        "total_created": total_created,
        "results": results,
    }


@router.post("/issue_patches/{patch_id}/apply")
def apply_issue_patch(patch_id: str, db: Session = Depends(get_db)):
    from ..models import IssuePatch
    from ..engine.patch import apply_patch
    p = db.query(IssuePatch).filter_by(id=patch_id).first()
    if not p:
        raise HTTPException(404, "patch not found")
    ok, msg = apply_patch(db, p)
    if not ok:
        raise HTTPException(400, msg)
    return {"ok": True, "patch": _patch_dict(p)}


@router.post("/issue_patches/{patch_id}/reject")
def reject_issue_patch(patch_id: str, db: Session = Depends(get_db)):
    from ..models import IssuePatch
    p = db.query(IssuePatch).filter_by(id=patch_id).first()
    if not p:
        raise HTTPException(404, "patch not found")
    if p.status != "pending":
        raise HTTPException(400, f"patch 当前状态是 {p.status}")
    p.status = "rejected"
    db.commit()
    return {"ok": True, "patch": _patch_dict(p)}


@router.post("/issue_patches/{patch_id}/undo")
def undo_issue_patch(patch_id: str, db: Session = Depends(get_db)):
    from ..models import IssuePatch
    from ..engine.patch import undo_patch
    p = db.query(IssuePatch).filter_by(id=patch_id).first()
    if not p:
        raise HTTPException(404, "patch not found")
    ok, msg = undo_patch(db, p)
    if not ok:
        raise HTTPException(400, msg)
    return {"ok": True, "patch": _patch_dict(p)}


@router.get("/issue_patches/{patch_id}/preview")
def preview_issue_patch(patch_id: str, db: Session = Depends(get_db)):
    from ..models import IssuePatch
    from ..engine.patch import preview_patch
    p = db.query(IssuePatch).filter_by(id=patch_id).first()
    if not p:
        raise HTTPException(404, "patch not found")
    return preview_patch(db, p)


# ─── scene_continuity ──────────────────────────────────────────

class SceneScanRequest(BaseModel):
    scope: str = "recent"
    tick_from: Optional[int] = None
    tick_to: Optional[int] = None
    provider: Optional[str] = None


@router.post("/worlds/{world_id}/scene_continuity/scan")
def scan_scene_continuity(
    world_id: str, payload: SceneScanRequest, db: Session = Depends(get_db),
):
    from ..engine.scene_continuity import run_scene_scan
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    run = run_scene_scan(
        db, world,
        scope=payload.scope or "recent",
        tick_from=payload.tick_from, tick_to=payload.tick_to,
        provider_key=payload.provider,
    )
    issues = (db.query(ConsistencyIssue)
              .filter_by(scan_id=run.id)
              .order_by(ConsistencyIssue.created_at.desc()).all())
    return {"scan": _scan_dict(run), "issues": [_issue_dict(i) for i in issues]}

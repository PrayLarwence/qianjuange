from __future__ import annotations
import threading
import uuid
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Job:
    id: str
    world_id: str
    kind: str
    status: str = "pending"
    cancel_event: threading.Event = field(default_factory=threading.Event)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    narration: str = ""
    error: str | None = None
    result: Any = None
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    progress_message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "world_id": self.world_id,
            "kind": self.kind,
            "status": self.status,
            "tool_calls": self.tool_calls,
            "narration": self.narration,
            "error": self.error,
            "result": self.result,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "progress_message": self.progress_message,
            "elapsed_seconds": (self.finished_at or time.time()) - self.started_at,
            "cancellable": self.status in ("pending", "running"),
        }

    def is_cancelled(self) -> bool:
        return self.cancel_event.is_set()


_JOBS: dict[str, Job] = {}
_LOCK = threading.Lock()
_MAX_AGE_SECONDS = 3600
_MAX_JOBS = 200


def create_job(world_id: str, kind: str) -> Job:
    _gc_locked()
    job = Job(id=f"job_{uuid.uuid4().hex[:12]}", world_id=world_id, kind=kind)
    with _LOCK:
        _JOBS[job.id] = job
    return job


def get_job(job_id: str) -> Job | None:
    return _JOBS.get(job_id)


def cancel_job(job_id: str) -> bool:
    job = _JOBS.get(job_id)
    if not job:
        return False
    job.cancel_event.set()
    return True


def _gc_locked() -> None:
    with _LOCK:
        if len(_JOBS) < _MAX_JOBS:
            now = time.time()
            stale = [jid for jid, j in _JOBS.items()
                     if j.status not in ("running", "pending") and (now - (j.finished_at or j.started_at)) > _MAX_AGE_SECONDS]
            for jid in stale:
                _JOBS.pop(jid, None)
            return
        ordered = sorted(_JOBS.items(), key=lambda kv: kv[1].finished_at or kv[1].started_at)
        for jid, j in ordered:
            if len(_JOBS) <= _MAX_JOBS // 2:
                break
            if j.status not in ("running", "pending"):
                _JOBS.pop(jid, None)

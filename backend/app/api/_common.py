"""routes 拆分后的共享 util。

- `_new_id` / `_id_prefix_for`：id 生成
- `_fork_branch`：分支克隆（暂存于 routes.py，后续若被多个子 router 用到再迁过来）
"""
from __future__ import annotations
import uuid


def _new_id(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:10]}"


def _id_prefix_for(old_id: str) -> str:
    if not old_id or "_" not in old_id:
        return "ent"
    return old_id.split("_", 1)[0]

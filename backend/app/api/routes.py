"""主 API router 聚合点。

所有具体业务端点已拆到同目录下的 *_api.py 子模块；本文件只负责 include。
新增子 router 时，添加 import + include_router 两行即可。
"""
from __future__ import annotations
import logging
from fastapi import APIRouter

log = logging.getLogger(__name__)
router = APIRouter()

from .manuscript_api import router as _manuscript_router
router.include_router(_manuscript_router)
from .consistency_api import router as _consistency_router
router.include_router(_consistency_router)
from .entities_api import router as _entities_router
router.include_router(_entities_router)
from .llm_api import router as _llm_router
router.include_router(_llm_router)
from .templates_api import router as _templates_router
router.include_router(_templates_router)
from .chapters_api import router as _chapters_router
router.include_router(_chapters_router)
from .events_api import router as _events_router
router.include_router(_events_router)
from .manuscript_render_api import router as _manuscript_render_router
router.include_router(_manuscript_render_router)
from .novelize_api import router as _novelize_router
router.include_router(_novelize_router)
from .export_novel_api import router as _export_novel_router
router.include_router(_export_novel_router)
from .explore_api import router as _explore_router
router.include_router(_explore_router)
from .history_api import router as _history_router
router.include_router(_history_router)
from .step_api import router as _step_router
router.include_router(_step_router)
from .branches_api import router as _branches_router
router.include_router(_branches_router)
from .timeline_api import router as _timeline_router
router.include_router(_timeline_router)
from .quick_create_api import router as _quick_create_router
router.include_router(_quick_create_router)
from .worlds_api import router as _worlds_router
router.include_router(_worlds_router)
from .world_settings_api import router as _world_settings_router
router.include_router(_world_settings_router)
from .agent_pipeline_api import router as _agent_pipeline_router
router.include_router(_agent_pipeline_router)

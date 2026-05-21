"""Agent pipeline 配置 schema + 全局 default 持久化。

存储模型：
- 全局 default：data/agent_pipeline_default.json，启动时 ensure 写出
- 世界级覆盖：World.agent_pipeline JSON 字段，None 时 fallback 到全局 default

config 形状（Pydantic model 自动校验）：
{
  "directors": [{name, model, system_prompt_extra, max_hops}],   # 1..MAX_DIRECTORS
  "authors":   [{name, model, system_prompt_extra}],             # 固定 1（schema 限制）
  "critics":   [{name, model, focus, severity}],                 # 0..MAX_CRITICS
  "max_critic_retries": 3,
  "critic_mode": "parallel" | "serial",
  "budget": {"max_llm_calls": 20, "max_wall_seconds": 300},
}
"""
from __future__ import annotations
import json
from pathlib import Path
from threading import RLock
from typing import Optional, Literal

from pydantic import BaseModel, Field, field_validator


MAX_DIRECTORS = 3
MAX_AUTHORS = 1
MAX_CRITICS = 5
MAX_RETRIES_HARD_CAP = 5  # 用户在 UI 改 max_critic_retries 时不能超过这个

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
DEFAULT_PATH = DATA_DIR / "agent_pipeline_default.json"

_lock = RLock()


class DirectorAgent(BaseModel):
    name: str = Field(default="director", min_length=1, max_length=64)
    model: str = ""  # 空 = 用全局 active provider 的默认 model
    system_prompt_extra: str = ""
    max_hops: int = Field(default=8, ge=1, le=20)


class AuthorAgent(BaseModel):
    name: str = Field(default="author", min_length=1, max_length=64)
    model: str = ""
    system_prompt_extra: str = ""


class CriticAgent(BaseModel):
    name: str = Field(default="critic", min_length=1, max_length=64)
    model: str = ""
    focus: str = Field(default="", max_length=500)  # 自然语言描述这个 critic 关注什么
    severity: Literal["lenient", "normal", "strict"] = "normal"
    # general = 只看这一段定稿; arc = 额外吃章节 recap, 关切跨 tick 一致性 / 主线推进
    kind: Literal["general", "arc"] = "general"


class BudgetConfig(BaseModel):
    max_llm_calls: int = Field(default=20, ge=1, le=200)
    max_wall_seconds: int = Field(default=300, ge=10, le=3600)


class PipelineConfig(BaseModel):
    directors: list[DirectorAgent] = Field(default_factory=lambda: [DirectorAgent()])
    authors: list[AuthorAgent] = Field(default_factory=lambda: [AuthorAgent()])
    critics: list[CriticAgent] = Field(default_factory=list)
    max_critic_retries: int = Field(default=3, ge=0, le=MAX_RETRIES_HARD_CAP)
    critic_mode: Literal["parallel", "serial"] = "parallel"
    budget: BudgetConfig = Field(default_factory=BudgetConfig)

    @field_validator("directors")
    @classmethod
    def _check_directors(cls, v):
        if not v:
            raise ValueError("至少需要 1 个 director")
        if len(v) > MAX_DIRECTORS:
            raise ValueError(f"director 最多 {MAX_DIRECTORS} 个")
        return v

    @field_validator("authors")
    @classmethod
    def _check_authors(cls, v):
        if len(v) != MAX_AUTHORS:
            raise ValueError(f"author 必须是 {MAX_AUTHORS} 个")
        return v

    @field_validator("critics")
    @classmethod
    def _check_critics(cls, v):
        if len(v) > MAX_CRITICS:
            raise ValueError(f"critic 最多 {MAX_CRITICS} 个")
        return v


def _builtin_default() -> PipelineConfig:
    return PipelineConfig(
        directors=[DirectorAgent(name="director", system_prompt_extra="")],
        authors=[AuthorAgent(name="author", system_prompt_extra="")],
        critics=[],
        max_critic_retries=3,
        critic_mode="parallel",
        budget=BudgetConfig(),
    )


def load_global_default() -> PipelineConfig:
    """从 data/agent_pipeline_default.json 读全局 default。
    文件不存在或解析失败时返回内置 default 并尝试写出。
    """
    with _lock:
        if DEFAULT_PATH.exists():
            try:
                raw = json.loads(DEFAULT_PATH.read_text(encoding="utf-8"))
                return PipelineConfig.model_validate(raw)
            except Exception:
                pass
        cfg = _builtin_default()
        try:
            save_global_default(cfg)
        except Exception:
            pass
        return cfg


def save_global_default(cfg: PipelineConfig) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with _lock:
        DEFAULT_PATH.write_text(
            json.dumps(cfg.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def resolve_for_world(world_pipeline: Optional[dict]) -> PipelineConfig:
    """给 World.agent_pipeline 字段算实际生效的 pipeline。
    None / 空 dict / 解析失败 → fallback 到全局 default。
    """
    if not world_pipeline:
        return load_global_default()
    try:
        return PipelineConfig.model_validate(world_pipeline)
    except Exception:
        return load_global_default()


LIMITS = {
    "max_directors": MAX_DIRECTORS,
    "max_authors": MAX_AUTHORS,
    "max_critics": MAX_CRITICS,
    "max_retries_hard_cap": MAX_RETRIES_HARD_CAP,
}

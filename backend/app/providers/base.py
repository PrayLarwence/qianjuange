from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal, Protocol


Role = Literal["system", "user", "assistant", "tool"]


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Message:
    role: Role
    content: str = ""
    tool_call_id: str | None = None
    tool_name: str | None = None
    tool_calls: list["ToolCall"] = field(default_factory=list)


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass
class LLMResponse:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)
    usage: dict[str, Any] = field(default_factory=dict)


class LLMProvider(Protocol):
    name: str

    def chat(
        self,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec],
        max_tokens: int = 2048,
        temperature: float = 0.7,
        timeout: float = 120.0,
    ) -> LLMResponse: ...


class BaseProvider:
    """所有 provider 子类的共同基类。

    子类只要 override 类变量（name/label/default_*/env_*），就能自动:
    - 注册到 PROVIDER_CLASSES（通过 __init_subclass__）
    - 自动派生 PROVIDER_META（前端展示）
    - 自动派生 DEFAULTS（config 默认值）
    - 自动派生 ENV_KEYS（环境变量兜底）
    """

    # 必填
    name: ClassVar[str] = ""
    label: ClassVar[str] = ""

    # 模型
    default_model: ClassVar[str] = ""
    default_models: ClassVar[list[str]] = []  # 前端下拉建议
    default_base_url: ClassVar[str] = ""

    # 环境变量名（None 表示该字段不从 env 读）
    env_api_key: ClassVar[str | None] = None
    env_model: ClassVar[str | None] = None
    env_base_url: ClassVar[str | None] = None

    # 能力 / UI
    needs_api_key: ClassVar[bool] = True
    supports_native_tools: ClassVar[bool] = True
    homepage: ClassVar[str] = ""

    # ─── 自动注册 ─────────────────────────────────────
    def __init_subclass__(cls, **kw: Any) -> None:
        super().__init_subclass__(**kw)
        # 用 cls.__dict__ 而不是 getattr，避免继承到父类的 _abstract
        if cls.__dict__.get("_abstract", False):
            return
        if cls.name:
            from . import registry
            registry.register(cls)


def collect_kwargs(provider_name: str, cfg_entry: dict[str, Any]) -> dict[str, Any]:
    """从 config["providers"][name] 抽出构造 kwargs。

    - api_key / model / base_url 三字段，按存在与非空筛选
    - 调用方决定是否过滤（例如 ollama 不传 api_key）
    """
    kwargs: dict[str, Any] = {}
    if cfg_entry.get("api_key"):
        kwargs["api_key"] = cfg_entry["api_key"]
    if cfg_entry.get("model"):
        kwargs["model"] = cfg_entry["model"]
    if cfg_entry.get("base_url"):
        kwargs["base_url"] = cfg_entry["base_url"]
    return kwargs

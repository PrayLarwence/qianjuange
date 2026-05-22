"""新增 provider 的契约测试 (zhipu/qwen/moonshot/doubao/siliconflow/grok/lmstudio/ai302/gemini).

每家覆盖:
- 注册到 PROVIDER_CLASSES + meta 字段齐全
- 默认 model / base_url / env_api_key 与类属性一致
- chat 走基类 (OAI 兼容那 8 家) 或独立实现 (gemini)
- supports_listing 与 list_models_supported 类属性一致
- _build_headers 输出符合各家约定 (Authorization Bearer / x-goog-api-key)
- list_models 路径 / 解析 (启用动态拉取的 7 家)

不打真 API; httpx.Client 用 monkeypatch 替成 FakeClient.
"""
from __future__ import annotations

from typing import Any

import pytest


# ─── 配置: provider name → 期望属性 ───
OAI_COMPAT_PROVIDERS = {
    "zhipu":       {"base_url": "https://open.bigmodel.cn/api/paas/v4",       "env": "ZHIPU_API_KEY",       "listing": True},
    "qwen":        {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "env": "DASHSCOPE_API_KEY", "listing": False},
    "moonshot":    {"base_url": "https://api.moonshot.cn/v1",                 "env": "MOONSHOT_API_KEY",    "listing": True},
    "doubao":      {"base_url": "https://ark.cn-beijing.volces.com/api/v3",   "env": "ARK_API_KEY",         "listing": False},
    "siliconflow": {"base_url": "https://api.siliconflow.cn/v1",              "env": "SILICONFLOW_API_KEY", "listing": True},
    "grok":        {"base_url": "https://api.x.ai/v1",                        "env": "XAI_API_KEY",         "listing": True},
    "ai302":       {"base_url": "https://api.302.ai/v1",                      "env": "AI302_API_KEY",       "listing": True},
}


@pytest.mark.parametrize("name", list(OAI_COMPAT_PROVIDERS.keys()))
def test_oai_compat_provider_registered_with_meta(name):
    from app.providers import PROVIDER_CLASSES, registry
    cls = PROVIDER_CLASSES[name]
    cfg = OAI_COMPAT_PROVIDERS[name]
    meta = registry.provider_meta()[name]

    assert cls.default_base_url == cfg["base_url"]
    assert cls.env_api_key == cfg["env"]
    assert meta["label"]
    assert meta["needs_api_key"] is True
    assert meta["supports_native_tools"] is True
    assert meta["supports_listing"] is cfg["listing"]
    assert meta["homepage"].startswith("http")
    assert meta["default_models"], f"{name} default_models 不能为空"


@pytest.mark.parametrize("name", list(OAI_COMPAT_PROVIDERS.keys()))
def test_oai_compat_inherits_compat_chat(name):
    from app.providers import PROVIDER_CLASSES
    from app.providers.openai_compat import OpenAICompatibleProvider
    cls = PROVIDER_CLASSES[name]
    # 不应该重复实现 chat
    assert cls.chat is OpenAICompatibleProvider.chat


@pytest.mark.parametrize("name", list(OAI_COMPAT_PROVIDERS.keys()))
def test_oai_compat_build_headers_uses_bearer(name):
    from app.providers import PROVIDER_CLASSES
    cls = PROVIDER_CLASSES[name]
    p = cls(api_key="sk-test-123")
    h = p._build_headers()
    assert h["Authorization"] == "Bearer sk-test-123"
    assert h["Content-Type"] == "application/json"


@pytest.mark.parametrize("name", [n for n, c in OAI_COMPAT_PROVIDERS.items() if c["listing"]])
def test_oai_compat_list_models_hits_models_endpoint(name, monkeypatch):
    """启用 list_models 的 provider 应当 GET {base_url}/models 并解析 data 字段."""
    from app.providers import PROVIDER_CLASSES

    captured = {}

    class FakeResp:
        def raise_for_status(self): pass
        def json(self):
            return {"data": [{"id": "model-a"}, {"id": "model-b"}]}

    class FakeClient:
        def __init__(self, *a, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, url, headers):
            captured["url"] = url
            captured["headers"] = headers
            return FakeResp()

    import app.providers.openai_compat as oc
    monkeypatch.setattr(oc, "httpx", type("M", (), {"Client": FakeClient}))

    cls = PROVIDER_CLASSES[name]
    p = cls(api_key="sk-test")
    models = p.list_models()
    assert len(models) == 2
    assert captured["url"] == f"{cls.default_base_url}/models"
    assert captured["headers"]["Authorization"] == "Bearer sk-test"


# ─── LM Studio 单独测 (无需 api_key) ───

def test_lmstudio_does_not_need_api_key():
    from app.providers import LMStudioProvider, registry
    meta = registry.provider_meta()["lmstudio"]
    assert meta["needs_api_key"] is False
    assert meta["supports_listing"] is True
    p = LMStudioProvider()
    # 本地占位 key, 但不强求用户配置
    assert p.api_key == "lm-studio"
    assert p.base_url == "http://localhost:1234/v1"


def test_lmstudio_uses_compat_chat():
    from app.providers import LMStudioProvider
    from app.providers.openai_compat import OpenAICompatibleProvider
    assert LMStudioProvider.chat is OpenAICompatibleProvider.chat


def test_get_provider_lmstudio_skips_api_key(monkeypatch):
    """ollama 风格: needs_api_key=False, get_provider 不应传 api_key kwarg."""
    from app.providers import get_provider, PROVIDER_CLASSES
    captured = {}

    class FakeLMS:
        name = "lmstudio"
        needs_api_key = False
        def __init__(self, **kw):
            captured.update(kw)

    monkeypatch.setitem(PROVIDER_CLASSES, "lmstudio", FakeLMS)
    monkeypatch.setattr("app.providers.load_config",
                        lambda: {"active": "lmstudio",
                                 "providers": {"lmstudio": {"api_key": "ignored",
                                                            "model": "local-model",
                                                            "base_url": "http://localhost:1234/v1"}}})
    get_provider("lmstudio")
    assert "api_key" not in captured
    assert captured.get("model") == "local-model"


# ─── Gemini 独立协议 ───

def test_gemini_registered_with_meta():
    from app.providers import PROVIDER_CLASSES, GeminiProvider, registry
    assert PROVIDER_CLASSES["gemini"] is GeminiProvider
    meta = registry.provider_meta()["gemini"]
    assert meta["label"] == "Google Gemini"
    assert meta["supports_listing"] is True
    assert meta["needs_api_key"] is True
    assert "gemini-2.5-pro" in meta["default_models"]


def test_gemini_does_not_inherit_oai_compat():
    """Gemini 不走 OpenAI 兼容, 应当是独立的 BaseProvider 子类."""
    from app.providers import GeminiProvider
    from app.providers.base import BaseProvider
    from app.providers.openai_compat import OpenAICompatibleProvider
    assert issubclass(GeminiProvider, BaseProvider)
    assert not issubclass(GeminiProvider, OpenAICompatibleProvider)


def test_gemini_build_headers_uses_x_goog_api_key():
    from app.providers import GeminiProvider
    p = GeminiProvider(api_key="AIza-test")
    h = p._build_headers()
    assert h["x-goog-api-key"] == "AIza-test"
    assert "Authorization" not in h


def test_gemini_chat_posts_to_generate_content(monkeypatch):
    from app.providers import GeminiProvider, Message

    captured = {}

    class FakeResp:
        def raise_for_status(self): pass
        def json(self):
            return {
                "candidates": [{
                    "content": {
                        "parts": [
                            {"text": "hi from gemini"},
                            {"functionCall": {"name": "tool_x", "args": {"a": 1}}},
                        ],
                    },
                }],
                "usageMetadata": {"totalTokenCount": 42},
            }

    class FakeClient:
        def __init__(self, *a, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def post(self, url, json, headers):
            captured["url"] = url
            captured["payload"] = json
            captured["headers"] = headers
            return FakeResp()

    import app.providers.gemini as gm
    monkeypatch.setattr(gm, "httpx", type("M", (), {"Client": FakeClient}))

    p = GeminiProvider(api_key="AIza-x", model="gemini-2.5-flash")
    resp = p.chat(
        system="You are helpful.",
        messages=[Message(role="user", content="ping")],
        tools=[],
    )
    assert resp.text == "hi from gemini"
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].name == "tool_x"
    assert resp.tool_calls[0].arguments == {"a": 1}
    assert captured["url"].endswith("/models/gemini-2.5-flash:generateContent")
    # systemInstruction 拆出去, 不放进 contents
    assert captured["payload"]["systemInstruction"]["parts"][0]["text"] == "You are helpful."
    assert captured["payload"]["contents"][0]["role"] == "user"
    assert captured["headers"]["x-goog-api-key"] == "AIza-x"
    assert resp.usage["totalTokenCount"] == 42


def test_gemini_assistant_message_maps_to_model_role():
    """Gemini 不识别 'assistant' 这个 role, 必须映射为 'model'."""
    from app.providers.gemini import _to_gemini_contents
    from app.providers import Message, ToolCall

    out = _to_gemini_contents([
        Message(role="user", content="hi"),
        Message(role="assistant", content="ok", tool_calls=[
            ToolCall(id="x", name="tool_a", arguments={"k": "v"}),
        ]),
        Message(role="tool", content="result here", tool_call_id="x", tool_name="tool_a"),
    ])
    assert out[0]["role"] == "user"
    assert out[1]["role"] == "model"
    # assistant 的 tool_calls 应转成 functionCall part
    assert out[1]["parts"][1]["functionCall"]["name"] == "tool_a"
    # tool 结果当 user 角色, functionResponse part
    assert out[2]["role"] == "user"
    assert out[2]["parts"][0]["functionResponse"]["name"] == "tool_a"


def test_gemini_strip_schema_removes_unsupported_fields():
    """OpenAPI schema 里 'additionalProperties' / '$schema' 等会让 Gemini 报 400, 必须砍掉."""
    from app.providers.gemini import _strip_schema
    cleaned = _strip_schema({
        "type": "object",
        "additionalProperties": False,
        "$schema": "http://...",
        "properties": {
            "x": {"type": "string", "additionalProperties": False, "description": "hi"},
        },
        "required": ["x"],
    })
    assert "additionalProperties" not in cleaned
    assert "$schema" not in cleaned
    assert cleaned["properties"]["x"] == {"type": "string", "description": "hi"}
    assert cleaned["required"] == ["x"]


def test_gemini_list_models_normalizes_models_prefix(monkeypatch):
    from app.providers import GeminiProvider

    class FakeResp:
        def raise_for_status(self): pass
        def json(self):
            return {"models": [
                {
                    "name": "models/gemini-2.5-pro",
                    "displayName": "Gemini 2.5 Pro",
                    "inputTokenLimit": 1000000,
                    "supportedGenerationMethods": ["generateContent", "countTokens"],
                },
                {
                    "name": "models/embedding-001",
                    "displayName": "Embedding",
                    "supportedGenerationMethods": ["embedContent"],  # 应被过滤
                },
            ]}

    captured = {}
    class FakeClient:
        def __init__(self, *a, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, url, headers):
            captured["url"] = url
            return FakeResp()

    import app.providers.gemini as gm
    monkeypatch.setattr(gm, "httpx", type("M", (), {"Client": FakeClient}))

    p = GeminiProvider(api_key="AIza-x")
    models = p.list_models()
    assert len(models) == 1
    assert models[0]["id"] == "gemini-2.5-pro"
    assert models[0]["context_length"] == 1000000
    assert captured["url"].endswith("/models")


# ─── 全员都能通过 get_provider 出来不出错 (smoke) ───

@pytest.mark.parametrize("name", [
    "zhipu", "qwen", "moonshot", "doubao", "siliconflow",
    "grok", "lmstudio", "ai302", "gemini",
])
def test_get_provider_can_construct_each(name, monkeypatch):
    """走 get_provider() 全链路, 确保 config 默认条目能让所有 provider 实例化不报错."""
    from app.providers import get_provider, PROVIDER_CLASSES, registry
    from app.providers.metrics_provider import MetricsProvider

    # 临时把 active 改成被测 provider, 走默认 config
    cls = PROVIDER_CLASSES[name]
    monkeypatch.setattr(
        "app.providers.load_config",
        lambda: {
            "active": name,
            "providers": {name: {
                "api_key": "" if not getattr(cls, "needs_api_key", True) else "sk-test",
                "model": cls.default_model,
                "base_url": cls.default_base_url,
            }},
        },
    )
    p = get_provider(name)
    # MetricsProvider 包装外层
    assert isinstance(p, MetricsProvider)
    # 内层是真正的 provider 实例
    assert isinstance(p._inner, cls)

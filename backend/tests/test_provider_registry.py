"""Provider registry 契约测试。

验证基类抽出 + 自动注册机制：
- 4 个现有 provider 都注册到位
- 元信息字段齐全（label / default_model / default_models / homepage）
- OpenAI 兼容基类自身不被注册（_abstract）
- 新增子类能自动加入
"""
from __future__ import annotations

import pytest


def test_all_four_providers_registered():
    from app.providers import PROVIDER_CLASSES
    assert set(PROVIDER_CLASSES.keys()) == {"claude", "openai", "deepseek", "ollama", "openrouter"}


def test_provider_meta_complete():
    from app.providers import registry
    meta = registry.provider_meta()
    for name in ("claude", "openai", "deepseek", "ollama", "openrouter"):
        m = meta[name]
        assert m["label"], f"{name} missing label"
        assert isinstance(m["default_models"], list) and m["default_models"], f"{name} missing default_models"
        assert "needs_api_key" in m
        assert "supports_native_tools" in m
        assert m["homepage"].startswith("http")


def test_ollama_does_not_need_api_key():
    from app.providers import registry
    assert registry.provider_meta()["ollama"]["needs_api_key"] is False
    assert registry.provider_meta()["ollama"]["supports_native_tools"] is False


def test_provider_defaults_match_class_attrs():
    from app.providers import registry, PROVIDER_CLASSES
    defaults = registry.provider_defaults()
    for name, cls in PROVIDER_CLASSES.items():
        assert defaults[name]["model"] == cls.default_model
        assert defaults[name]["base_url"] == cls.default_base_url
        assert defaults[name]["api_key"] == ""


def test_env_keys_match_class_attrs():
    from app.providers import registry, PROVIDER_CLASSES
    env_map = registry.env_keys()
    for name, cls in PROVIDER_CLASSES.items():
        assert env_map[name] == (cls.env_api_key, cls.env_model, cls.env_base_url)


def test_openai_compat_base_not_registered():
    """OpenAICompatibleProvider 是抽象基类，不应自己被注册。"""
    from app.providers import PROVIDER_CLASSES
    from app.providers.openai_compat import OpenAICompatibleProvider
    # 基类不在注册表里
    assert OpenAICompatibleProvider not in PROVIDER_CLASSES.values()
    # 但具体子类在
    assert PROVIDER_CLASSES["openai"].__bases__[0] is OpenAICompatibleProvider
    assert PROVIDER_CLASSES["deepseek"].__bases__[0] is OpenAICompatibleProvider


def test_subclass_auto_registers_and_unregisters():
    """新写一个子类应当自动出现在 PROVIDER_CLASSES，测完后清理。"""
    from app.providers import PROVIDER_CLASSES, registry
    from app.providers.openai_compat import OpenAICompatibleProvider

    class FakeKimi(OpenAICompatibleProvider):
        name = "fake_kimi_test"
        label = "Kimi (test)"
        default_model = "moonshot-v1-8k"
        default_base_url = "https://api.moonshot.cn/v1"
        env_api_key = "MOONSHOT_API_KEY"
        homepage = "https://platform.moonshot.cn"

    try:
        assert "fake_kimi_test" in PROVIDER_CLASSES
        meta = registry.provider_meta()["fake_kimi_test"]
        assert meta["label"] == "Kimi (test)"
        assert meta["needs_api_key"] is True
        assert meta["supports_native_tools"] is True
        # default_models 没设也不该崩
        assert meta["default_models"] == []
    finally:
        PROVIDER_CLASSES.pop("fake_kimi_test", None)


def test_openai_provider_uses_compat_chat(monkeypatch):
    """OpenAIProvider 现在继承自 OpenAICompatibleProvider，调用 chat 应走兼容路径。"""
    from app.providers import OpenAIProvider, Message
    from app.providers.openai_compat import OpenAICompatibleProvider

    captured = {}

    class FakeResp:
        def raise_for_status(self): pass
        def json(self):
            return {"choices": [{"message": {"content": "hi", "tool_calls": []}}], "usage": {"total_tokens": 5}}

    class FakeClient:
        def __init__(self, *a, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def post(self, url, json, headers):
            captured["url"] = url
            captured["model"] = json["model"]
            captured["auth"] = headers.get("Authorization", "")
            return FakeResp()

    import app.providers.openai_compat as oc
    monkeypatch.setattr(oc, "httpx", type("M", (), {"Client": FakeClient}))

    p = OpenAIProvider(api_key="sk-test", model="gpt-4o-mini")
    resp = p.chat(system="s", messages=[Message(role="user", content="x")], tools=[])
    assert resp.text == "hi"
    assert captured["url"].endswith("/chat/completions")
    assert captured["model"] == "gpt-4o-mini"
    assert captured["auth"] == "Bearer sk-test"
    # 确认是基类提供的实现
    assert OpenAIProvider.chat is OpenAICompatibleProvider.chat


def test_deepseek_inherits_compat_implementation():
    from app.providers import DeepSeekProvider
    from app.providers.openai_compat import OpenAICompatibleProvider
    assert DeepSeekProvider.chat is OpenAICompatibleProvider.chat
    p = DeepSeekProvider()
    assert p.base_url == "https://api.deepseek.com/v1"
    assert p.model == "deepseek-chat"


def test_get_provider_skips_api_key_when_not_needed(monkeypatch):
    """ollama 不该收到 api_key 即使 config 里塞了。"""
    from app.providers import get_provider, registry, PROVIDER_CLASSES
    captured = {}

    class FakeOllama:
        name = "ollama"
        needs_api_key = False
        def __init__(self, **kw):
            captured.update(kw)

    monkeypatch.setitem(PROVIDER_CLASSES, "ollama", FakeOllama)
    monkeypatch.setattr("app.providers.load_config",
                        lambda: {"active": "ollama",
                                 "providers": {"ollama": {"api_key": "should-be-dropped",
                                                          "model": "llama3.1",
                                                          "base_url": "http://localhost:11434"}}})

    get_provider("ollama")
    assert "api_key" not in captured
    assert captured.get("model") == "llama3.1"
    assert captured.get("base_url") == "http://localhost:11434"


def test_load_config_picks_up_newly_registered_provider():
    """注册一个新 provider，load_config 应该立刻给它返回默认条目。"""
    from app.providers import load_config, PROVIDER_CLASSES
    from app.providers.openai_compat import OpenAICompatibleProvider

    class FakeProvX(OpenAICompatibleProvider):
        name = "fake_provx_test"
        label = "ProvX"
        default_model = "x-default"
        default_base_url = "https://provx.example.com/v1"
        env_api_key = "PROVX_API_KEY"

    try:
        cfg = load_config()
        assert "fake_provx_test" in cfg["providers"]
        assert cfg["providers"]["fake_provx_test"]["model"] == "x-default"
        assert cfg["providers"]["fake_provx_test"]["base_url"] == "https://provx.example.com/v1"
    finally:
        PROVIDER_CLASSES.pop("fake_provx_test", None)


# ============ OpenRouter ============

def test_openrouter_registered_with_correct_meta():
    from app.providers import PROVIDER_CLASSES, OpenRouterProvider, registry
    assert PROVIDER_CLASSES["openrouter"] is OpenRouterProvider
    meta = registry.provider_meta()["openrouter"]
    assert meta["label"] == "OpenRouter"
    assert meta["needs_api_key"] is True
    assert meta["supports_native_tools"] is True
    assert meta["supports_listing"] is True
    assert meta["homepage"] == "https://openrouter.ai"
    assert "anthropic/claude-opus-4" in meta["default_models"]


def test_meta_supports_listing_defaults_false():
    from app.providers import registry
    meta = registry.provider_meta()
    # OpenRouter 显式 list_models_supported=True
    assert meta["openrouter"]["supports_listing"] is True
    # OpenAI/DeepSeek 没显式打开 (基类默认 False), 不会被前端误判为可拉取
    assert meta["openai"]["supports_listing"] is False
    assert meta["deepseek"]["supports_listing"] is False
    # Claude/Ollama 不继承 OpenAI 兼容基类, 也是 False
    assert meta["claude"]["supports_listing"] is False
    assert meta["ollama"]["supports_listing"] is False


def test_openrouter_injects_referer_and_title_headers():
    from app.providers import OpenRouterProvider
    p = OpenRouterProvider(api_key="sk-or-test")
    h = p._build_headers()
    assert h["Authorization"] == "Bearer sk-or-test"
    assert h["HTTP-Referer"].startswith("http")
    assert h["X-Title"] == "Narrative Sandbox"


def test_openrouter_uses_compat_chat_implementation():
    """openrouter 不该重复实现 chat, 复用基类."""
    from app.providers import OpenRouterProvider
    from app.providers.openai_compat import OpenAICompatibleProvider
    assert OpenRouterProvider.chat is OpenAICompatibleProvider.chat


def test_openrouter_list_models_supported():
    from app.providers import OpenRouterProvider
    assert OpenRouterProvider.list_models_supported is True


def test_openrouter_list_models_parses_data_field(monkeypatch):
    from app.providers import OpenRouterProvider

    fake_payload = {
        "data": [
            {"id": "anthropic/claude-opus-4", "name": "Claude Opus 4", "context_length": 200000,
             "pricing": {"prompt": "0.000015", "completion": "0.000075"}},
            {"id": "openai/gpt-4o", "name": "GPT-4o"},
        ]
    }

    class FakeResp:
        def raise_for_status(self): pass
        def json(self): return fake_payload

    captured = {}
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

    p = OpenRouterProvider(api_key="sk-or-test")
    models = p.list_models()
    assert len(models) == 2
    assert models[0]["id"] == "anthropic/claude-opus-4"
    assert captured["url"] == "https://openrouter.ai/api/v1/models"
    # referer/title 必须传给 GET /models, 不只是 chat
    assert captured["headers"]["HTTP-Referer"]
    assert captured["headers"]["X-Title"] == "Narrative Sandbox"


def test_list_models_unsupported_provider_raises():
    """ollama / claude 没开 list_models, 调用应抛 NotImplementedError."""
    from app.providers import ClaudeProvider
    # ClaudeProvider 没继承 OpenAICompatibleProvider, 根本没这方法
    assert not hasattr(ClaudeProvider, "list_models")


def test_list_models_endpoint_returns_normalized_models(client, monkeypatch):
    """API 端点 GET /llm_config/models?provider=openrouter."""
    from app.providers import PROVIDER_CLASSES

    class FakeOR:
        name = "openrouter"
        label = "OpenRouter"
        default_model = "openai/gpt-4o-mini"
        default_models = []
        default_base_url = "https://openrouter.ai/api/v1"
        env_api_key = None
        env_model = None
        env_base_url = None
        needs_api_key = True
        supports_native_tools = True
        homepage = "https://openrouter.ai"
        list_models_supported = True
        def __init__(self, **kw): pass
        def list_models(self, timeout=30.0):
            return [
                {"id": "openai/gpt-4o", "name": "GPT-4o", "context_length": 128000,
                 "pricing": {"prompt": "0.0025"}},
                {"id": "anthropic/claude-opus-4", "name": "Claude Opus 4"},
                {"id": "garbage"},  # 极简条目也该过
            ]

    monkeypatch.setitem(PROVIDER_CLASSES, "openrouter", FakeOR)

    r = client.get("/api/llm_config/models?provider=openrouter")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["count"] == 3
    # sort by id
    ids = [m["id"] for m in body["models"]]
    assert ids == sorted(ids)
    # 字段标准化: name 缺省落到 id
    garbage = next(m for m in body["models"] if m["id"] == "garbage")
    assert garbage["name"] == "garbage"
    assert garbage["context_length"] is None


def test_list_models_endpoint_unsupported_provider(client):
    """claude 不支持 list_models -> ok=False 但不 500."""
    r = client.get("/api/llm_config/models?provider=claude")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "不支持" in body["error"]
    assert body["models"] == []


def test_list_models_endpoint_unknown_provider(client):
    r = client.get("/api/llm_config/models?provider=nope")
    assert r.status_code == 400


def test_list_models_endpoint_api_error_reported(client, monkeypatch):
    """list_models 调用抛异常时 ok=False 并把信息回到前端."""
    from app.providers import PROVIDER_CLASSES

    class BoomOR:
        name = "openrouter"
        label = "OpenRouter"
        default_model = "openai/gpt-4o-mini"
        default_models = []
        default_base_url = "https://openrouter.ai/api/v1"
        env_api_key = None
        env_model = None
        env_base_url = None
        needs_api_key = True
        supports_native_tools = True
        homepage = "https://openrouter.ai"
        list_models_supported = True
        def __init__(self, **kw): pass
        def list_models(self, timeout=30.0):
            raise RuntimeError("network down")

    monkeypatch.setitem(PROVIDER_CLASSES, "openrouter", BoomOR)
    r = client.get("/api/llm_config/models?provider=openrouter")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "network down" in body["error"]

"""共享测试 fixture。

要点：
- 用 in-memory SQLite 隔离每个测试，绝不碰 data/world.db
- 用 monkeypatch 替换 app.models.db 里的全局 engine/SessionLocal，让 routes 的 Depends(get_db) 取到测试 db
- FakeProvider 用脚本化响应驱动 LLM 调用，避免真打网络
"""
from __future__ import annotations
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.db import Base
from app.providers.base import LLMResponse, ToolCall


# ----- 内存 DB -----

@pytest.fixture
def engine_mem():
    # StaticPool + check_same_thread=False：让所有连接共享同一个 SQLite 内存 db，
    # 否则 ":memory:" 每条新连接是一个独立的库，建表的连接和查表的连接看不到对方。
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    from app.models import world  # noqa: F401  必须先 import 让 ORM 注册到 Base
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine_mem):
    Session = sessionmaker(bind=engine_mem, autoflush=False, autocommit=False, future=True)
    session = Session()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(engine_mem, monkeypatch):
    """FastAPI TestClient + 内存 db。

    用 FastAPI 的 dependency_overrides 替换 get_db，
    比 monkeypatch 模块级 SessionLocal 更可靠（不被 import 链缓存）。
    """
    from sqlalchemy.orm import sessionmaker
    TestSession = sessionmaker(bind=engine_mem, autoflush=False, autocommit=False, future=True)

    # 阻止 startup 用真 engine 重建/迁移
    import app.models.db as dbmod
    monkeypatch.setattr(dbmod, "engine", engine_mem)
    monkeypatch.setattr(dbmod, "SessionLocal", TestSession)
    monkeypatch.setattr(dbmod, "_migrate", lambda: None)

    from fastapi.testclient import TestClient
    from app.main import app
    from app.models.db import get_db

    def override_get_db():
        s = TestSession()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()


# ----- LLM 替身 -----

class FakeProvider:
    """脚本化 LLM。每次 chat() 弹出一条预设响应。

    用法：
        provider = FakeProvider([
            LLMResponse(tool_calls=[ToolCall(id="1", name="add_event", arguments={...})]),
            LLMResponse(text="end"),
        ])
    """
    name = "fake"

    def __init__(self, scripted: list[LLMResponse] | None = None):
        self.scripted: list[LLMResponse] = list(scripted or [])
        self.calls: list[dict] = []  # 每次调用的入参快照

    def chat(self, system, messages, tools, max_tokens=2048, temperature=0.7, timeout=120.0):
        self.calls.append({
            "system": system,
            "msg_count": len(messages),
            "tools": [t.name for t in tools],
            "max_tokens": max_tokens,
        })
        if self.scripted:
            return self.scripted.pop(0)
        return LLMResponse(text="")


@pytest.fixture
def fake_llm():
    return FakeProvider()


def make_tool_call(name: str, **arguments) -> ToolCall:
    """便利函数：tool call 构造。"""
    import uuid
    return ToolCall(id=f"tc_{uuid.uuid4().hex[:6]}", name=name, arguments=arguments)


# ----- 数据工厂 -----

@pytest.fixture
def world_factory(db):
    """直接落库的世界 + main 分支创建器。绕过 LLM。"""
    from app.models import World, Branch
    import uuid

    def make(name: str = "测试世界", description: str = "", outline: str = "", rules: dict | None = None):
        wid = f"w_{uuid.uuid4().hex[:8]}"
        bid = f"br_{uuid.uuid4().hex[:8]}"
        w = World(id=wid, name=name, description=description, outline=outline,
                  rules=rules or {}, current_tick=0)
        db.add(w); db.flush()
        br = Branch(id=bid, world_id=wid, name="main", description="主线",
                    parent_branch_id=None, diverged_at_tick=0)
        db.add(br); db.flush()
        w.active_branch_id = bid
        db.commit()
        return w, br

    return make

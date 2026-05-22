"""OpenAI 兼容协议的通用 provider 基类。

子类只要声明类变量（name / label / default_model / default_base_url 等），
就能跑 OpenAI Chat Completions 协议（含 function calling）。

DeepSeek / Moonshot Kimi / 智谱 GLM / OpenRouter / Together / Groq 等都走这个。
"""
from __future__ import annotations
import json
import os
from typing import Any

import httpx

from .base import BaseProvider, LLMResponse, Message, ToolCall, ToolSpec


class OpenAICompatibleProvider(BaseProvider):
    """OpenAI Chat Completions 协议的通用客户端。

    子类应 override:
      name / label / default_model / default_base_url / env_api_key (其余可选)
    """
    _abstract: bool = True  # 不被 registry 自动登记

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ):
        env_key = self.env_api_key
        self.api_key = api_key or (os.getenv(env_key, "") if env_key else "")
        self.model = model or self.default_model
        self.base_url = (base_url or self.default_base_url).rstrip("/")

    def chat(
        self,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec],
        max_tokens: int = 2048,
        temperature: float = 0.7,
        timeout: float = 120.0,
    ) -> LLMResponse:
        oa_messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
        for m in messages:
            if m.role == "tool":
                oa_messages.append({
                    "role": "tool",
                    "tool_call_id": m.tool_call_id or "",
                    "content": m.content,
                })
            elif m.role == "assistant" and m.tool_calls:
                oa_messages.append({
                    "role": "assistant",
                    "content": m.content or None,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                            },
                        }
                        for tc in m.tool_calls
                    ],
                })
            else:
                oa_messages.append({"role": m.role, "content": m.content})

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": oa_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in tools
            ]
            payload["tool_choice"] = "auto"

        headers = self._build_headers()
        with httpx.Client(timeout=timeout) as client:
            r = client.post(f"{self.base_url}/chat/completions", json=payload, headers=headers)
            r.raise_for_status()
            data = r.json()

        choice = data["choices"][0]["message"]
        text = choice.get("content") or ""
        tool_calls: list[ToolCall] = []
        for tc in choice.get("tool_calls", []) or []:
            fn = tc.get("function", {})
            try:
                args = json.loads(fn.get("arguments", "{}") or "{}")
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(ToolCall(id=tc.get("id", ""), name=fn.get("name", ""), arguments=args))
        return LLMResponse(text=text, tool_calls=tool_calls, raw=data, usage=data.get("usage", {}))

    def _build_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    # ─── 可选: 动态拉模型列表 ─────────────────────────
    # 默认走 OpenAI 标准 GET /models, 子类可 override 走自己的
    list_models_path: str = "/models"
    list_models_supported: bool = False  # 子类显式打开

    def list_models(self, timeout: float = 30.0) -> list[dict[str, Any]]:
        """返回 [{"id": "...", "name": "...", ...}], 字段不规范化, 由前端自己挑."""
        if not self.list_models_supported:
            raise NotImplementedError(f"{self.name} does not support listing models")
        with httpx.Client(timeout=timeout) as client:
            r = client.get(f"{self.base_url}{self.list_models_path}", headers=self._build_headers())
            r.raise_for_status()
            data = r.json()
        # OpenAI / OpenRouter 都是 {"data": [...]}, 兜底直接返回根 list
        if isinstance(data, dict) and "data" in data:
            return data["data"]
        return data if isinstance(data, list) else []

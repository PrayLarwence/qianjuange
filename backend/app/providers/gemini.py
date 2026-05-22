"""Google Gemini - 原生 generateContent 协议.

不走 OpenAI 兼容, 协议完全不同:
- POST /v1beta/models/{model}:generateContent
- 角色: 'user' / 'model' (没有 assistant/system)
- system 在顶层 system_instruction
- tool 调用: parts[].functionCall {name, args}
- tool 结果: 当 'user' 角色, parts[].functionResponse {name, response}
- 字段名 snake_case 与 camelCase 都接受, 这里统一 camelCase.
"""
from __future__ import annotations
import os
from typing import Any, ClassVar

import httpx

from .base import BaseProvider, LLMResponse, Message, ToolCall, ToolSpec


class GeminiProvider(BaseProvider):
    name = "gemini"
    label = "Google Gemini"
    default_model = "gemini-2.5-pro"
    default_models = [
        "gemini-2.5-pro",
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
    ]
    default_base_url = "https://generativelanguage.googleapis.com/v1beta"
    env_api_key = "GOOGLE_API_KEY"
    env_model = "GEMINI_MODEL"
    homepage = "https://aistudio.google.com"

    list_models_supported: ClassVar[bool] = True

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
        contents = _to_gemini_contents(messages)
        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": temperature,
            },
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        if tools:
            payload["tools"] = [{
                "functionDeclarations": [
                    {
                        "name": t.name,
                        "description": t.description,
                        "parameters": _strip_schema(t.parameters),
                    }
                    for t in tools
                ],
            }]
            payload["toolConfig"] = {"functionCallingConfig": {"mode": "AUTO"}}

        url = f"{self.base_url}/models/{self.model}:generateContent"
        headers = self._build_headers()
        with httpx.Client(timeout=timeout) as client:
            r = client.post(url, json=payload, headers=headers)
            r.raise_for_status()
            data = r.json()

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        candidates = data.get("candidates") or []
        if candidates:
            parts = (candidates[0].get("content") or {}).get("parts") or []
            for idx, p in enumerate(parts):
                if "text" in p and p["text"]:
                    text_parts.append(p["text"])
                fc = p.get("functionCall")
                if fc:
                    tool_calls.append(ToolCall(
                        id=f"gemini-{idx}",
                        name=fc.get("name", ""),
                        arguments=fc.get("args") or {},
                    ))
        return LLMResponse(
            text="".join(text_parts),
            tool_calls=tool_calls,
            raw=data,
            usage=data.get("usageMetadata", {}) or {},
        )

    def _build_headers(self) -> dict[str, str]:
        return {
            "x-goog-api-key": self.api_key,
            "Content-Type": "application/json",
        }

    def list_models(self, timeout: float = 30.0) -> list[dict[str, Any]]:
        with httpx.Client(timeout=timeout) as client:
            r = client.get(f"{self.base_url}/models", headers=self._build_headers())
            r.raise_for_status()
            data = r.json()
        out: list[dict[str, Any]] = []
        # Gemini 返回 {"models": [{"name": "models/gemini-2.5-pro", "displayName": "...", ...}]}
        for m in data.get("models", []) or []:
            full = m.get("name", "")
            short = full.removeprefix("models/") if full.startswith("models/") else full
            # 只保留支持 generateContent 的
            methods = m.get("supportedGenerationMethods") or []
            if methods and "generateContent" not in methods:
                continue
            out.append({
                "id": short,
                "name": m.get("displayName") or short,
                "context_length": m.get("inputTokenLimit"),
                "pricing": None,
            })
        return out


_GEMINI_ALLOWED_SCHEMA_FIELDS = {
    "type", "format", "description", "nullable", "enum", "maxItems", "minItems",
    "properties", "required", "items", "propertyOrdering",
}


def _strip_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Gemini 对 OpenAPI schema 字段比较挑剔, 砍掉它不认的字段."""
    if not isinstance(schema, dict):
        return schema
    out: dict[str, Any] = {}
    for k, v in schema.items():
        if k not in _GEMINI_ALLOWED_SCHEMA_FIELDS:
            continue
        if k == "properties" and isinstance(v, dict):
            out[k] = {pk: _strip_schema(pv) for pk, pv in v.items()}
        elif k == "items" and isinstance(v, dict):
            out[k] = _strip_schema(v)
        else:
            out[k] = v
    return out


def _to_gemini_contents(messages: list[Message]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in messages:
        if m.role == "tool":
            # tool 结果当作 user 发回, 用 functionResponse part
            out.append({
                "role": "user",
                "parts": [{
                    "functionResponse": {
                        "name": m.tool_name or "",
                        "response": {"content": m.content},
                    },
                }],
            })
        elif m.role == "assistant":
            parts: list[dict[str, Any]] = []
            if m.content:
                parts.append({"text": m.content})
            for tc in m.tool_calls:
                parts.append({"functionCall": {"name": tc.name, "args": tc.arguments}})
            out.append({"role": "model", "parts": parts or [{"text": ""}]})
        else:
            out.append({"role": "user", "parts": [{"text": m.content}]})
    return out

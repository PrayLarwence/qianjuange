from __future__ import annotations
import json
import os
from typing import Any
import httpx
from .base import BaseProvider, LLMResponse, Message, ToolCall, ToolSpec


class ClaudeProvider(BaseProvider):
    name = "claude"
    label = "Claude (Anthropic)"
    default_model = "claude-opus-4-7"
    default_models = ["claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"]
    default_base_url = "https://api.anthropic.com"
    env_api_key = "ANTHROPIC_API_KEY"
    env_model = "CLAUDE_MODEL"
    homepage = "https://console.anthropic.com"

    def __init__(self, api_key: str | None = None, model: str | None = None, base_url: str | None = None):
        self.api_key = api_key or os.getenv(self.env_api_key or "", "")
        self.model = model or self.default_model
        self.base_url = (base_url or self.default_base_url).rstrip("/")

    def chat(self, system: str, messages: list[Message], tools: list[ToolSpec], max_tokens: int = 2048, temperature: float = 0.7, timeout: float = 120.0) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system,
            "messages": _to_claude_messages(messages),
        }
        if tools:
            payload["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.parameters}
                for t in tools
            ]

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        with httpx.Client(timeout=timeout) as client:
            r = client.post(f"{self.base_url}/v1/messages", json=payload, headers=headers)
            r.raise_for_status()
            data = r.json()

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in data.get("content", []):
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.get("id", ""),
                    name=block.get("name", ""),
                    arguments=block.get("input", {}) or {},
                ))
        return LLMResponse(
            text="".join(text_parts),
            tool_calls=tool_calls,
            raw=data,
            usage=data.get("usage", {}),
        )


def _to_claude_messages(messages: list[Message]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in messages:
        if m.role == "tool":
            out.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": m.tool_call_id or "",
                    "content": m.content,
                }],
            })
        elif m.role == "assistant":
            blocks: list[dict[str, Any]] = []
            if m.content:
                blocks.append({"type": "text", "text": m.content})
            for tc in m.tool_calls:
                blocks.append({"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.arguments})
            out.append({"role": "assistant", "content": blocks if blocks else m.content or ""})
        else:
            out.append({"role": "user", "content": m.content})
    return out

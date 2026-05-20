from __future__ import annotations
import json
import os
import re
from typing import Any
import httpx
from .base import LLMResponse, Message, ToolCall, ToolSpec


_TOOL_INSTR = (
    "You can call tools by emitting a fenced JSON block like:\n"
    "```tool\n"
    "{\"name\": \"<tool_name>\", \"arguments\": {<json args>}}\n"
    "```\n"
    "You may emit multiple tool blocks. Plain text outside blocks is narration."
)
_TOOL_BLOCK_RE = re.compile(r"```tool\s*(\{.*?\})\s*```", re.DOTALL)


class OllamaProvider:
    name = "ollama"

    def __init__(self, model: str = "llama3.1", base_url: str | None = None):
        self.model = model
        self.base_url = (base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")).rstrip("/")

    def chat(self, system: str, messages: list[Message], tools: list[ToolSpec], max_tokens: int = 2048, temperature: float = 0.7, timeout: float = 120.0) -> LLMResponse:
        sys_full = system
        if tools:
            sys_full += "\n\nAvailable tools:\n"
            for t in tools:
                sys_full += f"- {t.name}: {t.description}\n  schema: {json.dumps(t.parameters)}\n"
            sys_full += "\n" + _TOOL_INSTR

        ol_messages: list[dict[str, Any]] = [{"role": "system", "content": sys_full}]
        for m in messages:
            role = "user" if m.role == "tool" else m.role
            ol_messages.append({"role": role, "content": m.content})

        payload = {
            "model": self.model,
            "messages": ol_messages,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        with httpx.Client(timeout=timeout) as client:
            r = client.post(f"{self.base_url}/api/chat", json=payload)
            r.raise_for_status()
            data = r.json()

        text = (data.get("message") or {}).get("content", "")
        tool_calls: list[ToolCall] = []
        idx = 0
        for match in _TOOL_BLOCK_RE.finditer(text):
            try:
                obj = json.loads(match.group(1))
                name = obj.get("name", "")
                args = obj.get("arguments", {}) or {}
                if name:
                    tool_calls.append(ToolCall(id=f"ollama-{idx}", name=name, arguments=args))
                    idx += 1
            except json.JSONDecodeError:
                continue
        cleaned_text = _TOOL_BLOCK_RE.sub("", text).strip()
        return LLMResponse(text=cleaned_text, tool_calls=tool_calls, raw=data)

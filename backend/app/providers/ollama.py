from __future__ import annotations
import json
import os
import re
from typing import Any
import httpx
from .base import BaseProvider, LLMResponse, Message, ToolCall, ToolSpec


_TOOL_INSTR = (
    "You can call tools by emitting a fenced JSON block like:\n"
    "```tool\n"
    "{\"name\": \"<tool_name>\", \"arguments\": {<json args>}}\n"
    "```\n"
    "You may emit multiple tool blocks. Plain text outside blocks is narration."
)
_TOOL_BLOCK_RE = re.compile(r"```tool\s*(\{.*?\})\s*```", re.DOTALL)


class OllamaProvider(BaseProvider):
    name = "ollama"
    label = "Ollama (本地)"
    default_model = "llama3.1"
    default_models = ["llama3.1", "qwen2.5", "mistral", "deepseek-r1"]
    default_base_url = "http://localhost:11434"
    env_model = "OLLAMA_MODEL"
    env_base_url = "OLLAMA_BASE_URL"
    needs_api_key = False
    supports_native_tools = False
    homepage = "https://ollama.com"

    def __init__(self, model: str | None = None, base_url: str | None = None, **_kw: Any):
        # **_kw 吸收 api_key（即使误传也不报错，对齐其他 provider 签名）
        self.model = model or self.default_model
        env_url = os.getenv(self.env_base_url or "")
        self.base_url = (base_url or env_url or self.default_base_url).rstrip("/")

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

"""OpenRouter delta-emitter (OpenAI-compatible) — the hosted LLM seam impl. Default model: DeepSeek.

Vendor-agnostic on purpose: OpenRouter exposes an OpenAI-style /chat/completions with function-calling,
so we bind the model to the `propose_parameter_delta` function with forced `tool_choice` — its only
possible output is a validated `DeltaProposal` (no prose, no free Python, no safety scalar).

Config (the "input field"): `OPENROUTER_API_KEY` and optional `OPENROUTER_MODEL` env vars (see
`.env.example`), or pass them to the constructor. Implemented over httpx (no vendor SDK); a `post`
callable can be injected for tests so this is exercised with no key / no network.
"""

from __future__ import annotations

import json
import os

from packages.agents.llm_provider import LLMProvider
from packages.ledger.deltas import DeltaProposal, parameter_delta_tool_schema

_FN_NAME = "propose_parameter_delta"
_DEFAULT_MODEL = "deepseek/deepseek-chat"
_DEFAULT_BASE = "https://openrouter.ai/api/v1"
_SYSTEM = (
    "You are the geometric delta-emitter. Translate the user's intent into parameter deltas using the "
    "propose_parameter_delta function ONLY. Never write code or safety numbers. If the intent is "
    "ambiguous (missing value, unclear units, vague objective), call the function with "
    "request_clarification set and no deltas."
)

_CHAT_SYSTEM = (
    "You are a CAD copilot for a parametric mounting bracket. Reply conversationally in **Markdown** — "
    "briefly explain what you're doing or answer the question. When the user wants a parameter change, "
    "ALSO call the propose_parameter_delta function with the deltas. If the request is ambiguous "
    "(missing value/units or vague), call the function with request_clarification set plus 2-4 short "
    "`suggestions`, and ask the question in your reply. Never write code or safety numbers — proposed "
    "deltas are validated and applied by the system, and export stays blocked until a real FS exists.\n"
    "Tunable parameters (use these exact target_node paths):\n"
    "- domains.structure.skin_thickness_mm (1-5 mm)\n"
    "- domains.structure.internal_rib_spacing_mm (10-50 mm)"
)


class OpenRouterDeltaProvider(LLMProvider):
    def __init__(self, *, model: str | None = None, api_key: str | None = None,
                 base_url: str | None = None, max_tokens: int = 1024, post=None, stream_post=None) -> None:
        self.model = model or os.environ.get("OPENROUTER_MODEL", _DEFAULT_MODEL)
        self.api_key = api_key if api_key is not None else os.environ.get("OPENROUTER_API_KEY", "")
        self.base_url = base_url or os.environ.get("OPENROUTER_BASE_URL", _DEFAULT_BASE)
        self.max_tokens = max_tokens
        self._post = post  # injectable (url=, headers=, json=) -> dict, for tests
        self._stream_post = stream_post  # injectable (url=, headers=, json=) -> iterator[chunk dict]

    def _do_post(self, url: str, headers: dict, payload: dict) -> dict:
        if self._post is not None:
            return self._post(url=url, headers=headers, json=payload)
        import httpx
        resp = httpx.post(url, headers=headers, json=payload, timeout=60.0)
        resp.raise_for_status()
        return resp.json()

    def propose_delta(self, *, system: str, conversation: list[dict], ledger_json: str) -> DeltaProposal:
        if not self.api_key and self._post is None:
            return DeltaProposal(request_clarification="OPENROUTER_API_KEY is not set (see .env.example).")

        tool = {"type": "function", "function": {
            "name": _FN_NAME, "description": "Emit parameter deltas or request clarification.",
            "parameters": parameter_delta_tool_schema()}}
        payload = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": [{"role": "system", "content": system or _SYSTEM}] + conversation
                        + [{"role": "user", "content": f"Current ledger: {ledger_json}"}],
            "tools": [tool],
            "tool_choice": {"type": "function", "function": {"name": _FN_NAME}},
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        data = self._do_post(f"{self.base_url}/chat/completions", headers, payload)

        message = (data.get("choices") or [{}])[0].get("message", {}) or {}
        for call in message.get("tool_calls") or []:
            fn = call.get("function", {})
            if fn.get("name") == _FN_NAME:
                args = fn.get("arguments")
                parsed = json.loads(args) if isinstance(args, str) else args
                return DeltaProposal.model_validate(parsed)
        # forced tool_choice should prevent this; fail safe to a clarification rather than guess
        return DeltaProposal(request_clarification="No structured delta was produced.")

    # -- streaming conversational chat (prose + an optional delta proposal) --------------------
    def _do_stream(self, url: str, headers: dict, payload: dict):
        if self._stream_post is not None:
            yield from self._stream_post(url=url, headers=headers, json=payload)
            return
        import httpx
        with httpx.stream("POST", url, headers=headers, json=payload, timeout=120.0) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line or not line.startswith("data: "):
                    continue
                data = line[6:].strip()
                if data == "[DONE]":
                    return
                try:
                    yield json.loads(data)
                except json.JSONDecodeError:
                    continue

    def stream_chat(self, *, messages: list[dict], ledger_json: str):
        """Yield ('token', text), then ('proposal', DeltaProposal), then ('done', None) — or
        ('error', msg). The model produces prose AND an optional propose_parameter_delta call."""
        if not self.api_key and self._stream_post is None:
            yield ("error", "OPENROUTER_API_KEY is not set")
            return
        tool = {"type": "function", "function": {
            "name": _FN_NAME, "description": "Emit parameter deltas or request clarification.",
            "parameters": parameter_delta_tool_schema()}}
        payload = {
            "model": self.model, "max_tokens": self.max_tokens, "stream": True,
            "messages": [{"role": "system", "content": f"{_CHAT_SYSTEM}\n\nCurrent ledger: {ledger_json}"}]
                        + messages,
            "tools": [tool], "tool_choice": "auto",
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        tool_args: dict[int, str] = {}
        try:
            for chunk in self._do_stream(f"{self.base_url}/chat/completions", headers, payload):
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                if delta.get("content"):
                    yield ("token", delta["content"])
                for tc in delta.get("tool_calls") or []:
                    idx = tc.get("index", 0)
                    args = (tc.get("function") or {}).get("arguments") or ""
                    tool_args[idx] = tool_args.get(idx, "") + args
        except Exception as e:  # network / bad key / stream error
            yield ("error", str(e))
            return
        for args in tool_args.values():
            try:
                yield ("proposal", DeltaProposal.model_validate(json.loads(args)))
            except Exception:
                continue
        yield ("done", None)

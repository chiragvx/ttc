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


class OpenRouterDeltaProvider(LLMProvider):
    def __init__(self, *, model: str | None = None, api_key: str | None = None,
                 base_url: str | None = None, max_tokens: int = 1024, post=None) -> None:
        self.model = model or os.environ.get("OPENROUTER_MODEL", _DEFAULT_MODEL)
        self.api_key = api_key if api_key is not None else os.environ.get("OPENROUTER_API_KEY", "")
        self.base_url = base_url or os.environ.get("OPENROUTER_BASE_URL", _DEFAULT_BASE)
        self.max_tokens = max_tokens
        self._post = post  # injectable (url=, headers=, json=) -> dict, for tests

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

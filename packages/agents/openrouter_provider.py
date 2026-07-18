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
import logging
import os

from packages.agents.llm_provider import LLMProvider
from packages.agents.prompt_builder import build_system_prompt_from_json
from packages.ledger.deltas import DeltaProposal, parameter_delta_tool_schema

logger = logging.getLogger(__name__)

_FN_NAME = "propose_parameter_delta"
_DEFAULT_MODEL = "deepseek/deepseek-chat"
_DEFAULT_BASE = "https://openrouter.ai/api/v1"
# The streaming/conversational path (`stream_chat`, used by POST /chat) gets a higher cap than the
# single-shot delta-emitter path (`propose_delta`, used by POST /propose): a multi-part assembly
# reply can plausibly need prose PLUS several add_instance entries PLUS deltas PLUS a rationale, all
# in one completion, and the old shared 1024 cap could truncate that mid-tool-call-JSON with no
# signal (see FIX 1 in the investigation this responds to). 3072 is a deliberate middle ground: high
# enough that a real multi-op proposal has headroom, not so high that a stuck/rambling completion
# burns an outsized latency+cost tax before the cap kicks in.
_DEFAULT_CHAT_MAX_TOKENS = 3072
_SYSTEM = (
    "You are the geometric delta-emitter. Translate the user's intent into parameter deltas using the "
    "propose_parameter_delta function ONLY. Never write code or safety numbers. If the intent is "
    "ambiguous (missing value, unclear units, vague objective), call the function with "
    "request_clarification set and no deltas."
)


class OpenRouterDeltaProvider(LLMProvider):
    def __init__(self, *, model: str | None = None, api_key: str | None = None,
                 base_url: str | None = None, max_tokens: int = 1024,
                 chat_max_tokens: int = _DEFAULT_CHAT_MAX_TOKENS, post=None, stream_post=None) -> None:
        self.model = model or os.environ.get("OPENROUTER_MODEL", _DEFAULT_MODEL)
        self.api_key = api_key if api_key is not None else os.environ.get("OPENROUTER_API_KEY", "")
        self.base_url = base_url or os.environ.get("OPENROUTER_BASE_URL", _DEFAULT_BASE)
        self.max_tokens = max_tokens              # propose_delta (single-shot delta-emitter) cap
        self.chat_max_tokens = chat_max_tokens     # stream_chat (conversational) cap — see default above
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

    # -- vision judgment (blueprint self-check) --------------------------------------------------
    def judge_image(self, *, image_png: bytes, prompt: str, vision_model: str) -> "dict | None":
        """Send a PNG (base64 data URL) + `prompt` to a VISION-capable model and return its parsed
        JSON verdict `{"ok": bool, "issues": [{"severity","message"}], "summary": str}`. Goes through
        the SAME `_do_post` httpx seam as every other model call here (no vendor SDK — the CI lint that
        forbids `import anthropic` is satisfied). `vision_model` is REQUIRED and distinct from
        `self.model`: the default delta-emitter (deepseek/deepseek-chat) is text-only and cannot see —
        the caller passes a real vision model (packages/agents/vision_validator.py reads it from
        VISION_MODEL). Raises on transport error; the caller degrades gracefully.

        Returns **None** when no genuine JSON verdict can be parsed (absent/truncated/non-JSON reply).
        It must NEVER manufacture a `{"ok": True}` from an unparseable response — that would silently
        flip a real problem into a fabricated visual pass (2026-07-19 review, HIGH). None means
        "inconclusive"; the caller treats it as 'no visual verdict' and relies on the geometric check."""
        import base64
        b64 = base64.b64encode(image_png).decode("ascii")
        payload = {
            "model": vision_model,
            "max_tokens": self.max_tokens,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                ],
            }],
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        data = self._do_post(f"{self.base_url}/chat/completions", headers, payload)
        content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
        if isinstance(content, list):  # some providers return content as parts
            content = " ".join(p.get("text", "") for p in content if isinstance(p, dict))
        # tolerate a model that wraps its JSON in prose / a ```json fence
        start, end = content.find("{"), content.rfind("}")
        if start == -1 or end == -1:
            return None  # no JSON object at all — inconclusive, never a fabricated pass
        try:
            parsed = json.loads(content[start:end + 1])
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

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
        ('error', msg). The model produces prose AND an optional propose_parameter_delta call.

        Never silently empty end-to-end (see FIX 1 in the investigation this responds to): a
        malformed tool-call JSON, a truncated completion, or a turn that produced neither prose nor
        a usable proposal all yield an explicit ('error', ...) before the final ('done', None) —
        never just a bare done with nothing else."""
        if not self.api_key and self._stream_post is None:
            yield ("error", "OPENROUTER_API_KEY is not set")
            return
        tool = {"type": "function", "function": {
            "name": _FN_NAME, "description": "Emit parameter deltas or request clarification.",
            "parameters": parameter_delta_tool_schema()}}
        stable_prompt = build_system_prompt_from_json(ledger_json)
        payload = {
            "model": self.model, "max_tokens": self.chat_max_tokens, "stream": True,
            "messages": [{"role": "system", "content": f"{stable_prompt}\n\n## Current ledger\n{ledger_json}"}]
                        + messages,
            "tools": [tool], "tool_choice": "auto",
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        tool_args: dict[int, str] = {}
        saw_token = False
        finish_reason: str | None = None
        try:
            for chunk in self._do_stream(f"{self.base_url}/chat/completions", headers, payload):
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                choice = choices[0]
                delta = choice.get("delta") or {}
                if delta.get("content"):
                    saw_token = True
                    yield ("token", delta["content"])
                for tc in delta.get("tool_calls") or []:
                    idx = tc.get("index", 0)
                    args = (tc.get("function") or {}).get("arguments") or ""
                    tool_args[idx] = tool_args.get(idx, "") + args
                # some providers report finish_reason only on the final (often content-less) chunk —
                # keep the last non-null one seen, rather than requiring it ride with content/tool_calls.
                fr = choice.get("finish_reason")
                if fr:
                    finish_reason = fr
        except Exception as e:  # network / bad key / stream error
            yield ("error", str(e))
            yield ("done", None)  # keep the ('error', ...) then ('done', None) contract even here
            return
        saw_proposal = False
        for args in tool_args.values():
            try:
                proposal = DeltaProposal.model_validate(json.loads(args))
            except Exception as e:
                # a truncated/malformed tool-call arg string used to be dropped here with zero
                # signal (bare `except Exception: continue`) — that's the direct mechanism behind a
                # permanently-blank assistant bubble even though the request returned 200 OK. Log the
                # real parse exception for debugging, but don't leak it verbatim to the user.
                logger.warning("stream_chat: failed to parse tool-call arguments (%s)", e)
                yield ("error", "the model's proposal could not be parsed — try rephrasing or asking again")
                continue
            if proposal.deltas or proposal.feature_ops or proposal.instance_ops \
                    or proposal.connection_ops or proposal.coupling_ops or proposal.scope_proposal \
                    or proposal.request_clarification or proposal.suggestions:
                saw_proposal = True
                yield ("proposal", proposal)
            # else: a tool call that resolved to a fully empty DeltaProposal contributes nothing —
            # don't yield it (the frontend would no-op on it anyway) and don't count it as having
            # "seen" a proposal, so the no-response check below still fires for this genuinely
            # empty case instead of also emitting a redundant, contradictory empty-proposal event.
        if finish_reason not in (None, "stop", "tool_calls"):
            # e.g. "length" — cut off by the max_tokens cap; "content_filter" etc. also land here.
            yield ("error", "the response was cut off before finishing — try a shorter or simpler request")
        if not saw_token and not saw_proposal:
            yield ("error", "no response was generated for that message — try rephrasing or asking again")
        yield ("done", None)

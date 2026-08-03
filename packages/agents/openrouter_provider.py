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
import time

from packages.agents.llm_provider import LLMProvider
from packages.agents.prompt_builder import build_system_prompt_from_json
from packages.agents.research_provider import (
    ResearchFinding,
    ResearchQuery,
    get_research_provider,
    research_provider_configured,
    research_tool_schema,
)
from packages.ledger.deltas import DeltaProposal, parameter_delta_tool_schema

logger = logging.getLogger(__name__)

_FN_NAME = "propose_parameter_delta"
# The model's OWN decision to look up reference material mid-turn (2026-08-01), replacing the old
# deterministic pre-turn heuristic — see stream_chat's docstring and research_provider.py's module
# docstring for why. Offered as a second tool ALONGSIDE _FN_NAME only when a vendor is configured.
_RESEARCH_FN_NAME = "research_reference"
# 1 initial completion + at most 1 continuation once the model has a research result in hand — a
# hard cap, not configurable, so a model that keeps asking to research can never turn one chat turn
# into an unbounded chain of completion requests.
_MAX_RESEARCH_ROUNDS = 2
_DEFAULT_MODEL = "deepseek/deepseek-chat"
_DEFAULT_BASE = "https://openrouter.ai/api/v1"
# propose_delta (single-shot delta-emitter, called on slider-release / a chat turn's structured
# side) is idempotent to resend — nothing is applied to the ledger until it RETURNS a validated
# proposal — so a transient 429/5xx/timeout there is worth a small bounded retry. stream_chat
# deliberately does NOT get this: it's already mid-stream by the time a transport error can occur,
# and it has its own ('error', ...) event contract for exactly this failure class instead.
_PROPOSE_DELTA_RETRY_ATTEMPTS = 3
_PROPOSE_DELTA_RETRY_BASE_DELAY_S = 0.5
# The streaming/conversational path (`stream_chat`, used by POST /chat) gets a higher cap than the
# single-shot delta-emitter path (`propose_delta`, used by POST /propose): a multi-part assembly
# reply can plausibly need prose PLUS several add_instance entries PLUS deltas PLUS a rationale, all
# in one completion, and the old shared 1024 cap could truncate that mid-tool-call-JSON with no
# signal (see FIX 1 in the investigation this responds to). Raised three times on 2026-07-19/20
# (3072 -> 6144 -> 10240 -> 32768) against live repros in the same session: a "plenum + flange + 4
# runners" build truncated at 3072; an "8 runners" follow-up STILL truncated at 6144 (char ~6300); a
# 25-part recon-UAV airframe (multiple couplings + a full scope_proposal table) plausibly needed more
# than 10240 too. This is our OWN self-imposed cap, not a provider limit — checked live against
# OpenRouter's model API: the configured model has a 1M+-token context window and NO reported
# max_completion_tokens ceiling of its own, and completion pricing is ~$0.0002/1K tokens, so even a
# full 32768-token completion costs a fraction of a cent — there is no real cost/latency reason to
# keep this tight. A fixed cap will always lose to an unboundedly large ask eventually — this isn't
# trying to cover every request size, it's giving realistic multi-part builds real headroom. The
# genuinely load-bearing fix for whatever still exceeds this is the truncation DETECTION below
# (position-based, provider-independent), which makes the failure mode "an accurate, actionable
# error" instead of "wrong error" regardless of where the cap sits. Still bounded, not unlimited: an
# actually-stuck/rambling completion should still stop somewhere rather than run indefinitely.
_DEFAULT_CHAT_MAX_TOKENS = 32768
_SYSTEM = (
    "You are the geometric delta-emitter. Translate the user's intent into parameter deltas using the "
    "propose_parameter_delta function ONLY. Never write code or safety numbers. If the intent is "
    "ambiguous (missing value, unclear units, vague objective), call the function with "
    "request_clarification set and no deltas."
)


def _looks_truncated(args: str, e: "json.JSONDecodeError") -> bool:
    """True if a JSON parse failure on `args` looks like a stream cut off mid-generation, rather than
    a genuinely malformed-but-complete payload (2026-07-19 live repro, see stream_chat's own comment).

    "Unterminated string starting at: ..." is a SPECIAL case: `JSONDecodeError.pos` for this message
    points at the string's OPENING quote (where the unterminated literal began), not at the point the
    stream actually ran out — so it can sit far from `len(args)` even though hitting EOF mid-string is
    definitionally always a cut-off stream (a model does not deliberately emit a string it never
    closes). Every OTHER JSON error (missing delimiter, expecting a value, …) is truncation only when
    it lands AT the very end of the buffer — "expecting more input, found EOF" — not when there's
    trailing content after the error position, which means the payload was complete but syntactically
    wrong somewhere in the middle (a different, non-truncation failure)."""
    if "Unterminated string" in e.msg:
        return True
    return e.pos >= len(args)


def _extract_json_values(s: str) -> list[tuple[dict, str]]:
    """Repeatedly `raw_decode` complete top-level JSON values out of `s`, in order, returning
    [(value, remaining_string_after_it), ...]. Stops at the first position that doesn't decode
    (whitespace-only tail, or a genuine syntax error) — so a single valid value followed by
    non-JSON trailing junk still yields exactly one entry (the original 2026-07-19 recovery case).

    Exists because a model can second-guess itself mid-generation and emit MORE than one complete
    JSON object into a single tool call's arguments (2026-07-23 live repro on Qwen: a hesitant,
    wrongly-shaped "let me ask a clarifying question" draft — `deltas` as a list of "key=value"
    strings instead of the real schema — immediately followed by a second, complete, CORRECTLY
    shaped proposal covering the same build). The old single-`raw_decode` recovery only ever kept
    the FIRST complete value and logged everything after it as discarded "trailing junk" — which
    silently threw away a fully valid, later proposal because an earlier abandoned draft happened
    to parse (but fail schema validation) first."""
    out: list[tuple[dict, str]] = []
    rest = s.lstrip()
    decoder = json.JSONDecoder()
    while rest:
        try:
            value, end = decoder.raw_decode(rest)
        except json.JSONDecodeError:
            break
        rest = rest[end:].lstrip()
        out.append((value, rest))
    return out


def _is_retryable_transport_error(e: Exception) -> bool:
    """True for a 429, a 5xx, or a request timeout — the transient transport failures worth a bounded
    retry in propose_delta. Duck-typed rather than an `isinstance` check against `httpx`'s exception
    classes: an injected test double (see `post=` on the constructor) can raise a plain fake without
    needing to import/construct a real httpx exception, and this stays honest if `_do_post` is ever
    backed by something other than httpx. `httpx.HTTPStatusError` (raised by `raise_for_status()`)
    carries `.response.status_code`; `httpx.TimeoutException` and every subclass of it
    (`ConnectTimeout`, `ReadTimeout`, `WriteTimeout`, `PoolTimeout`) all have "Timeout" in the class
    name."""
    status = getattr(getattr(e, "response", None), "status_code", None)
    if isinstance(status, int) and (status == 429 or status >= 500):
        return True
    return "timeout" in type(e).__name__.lower()


def _recover_tool_call_proposal(args) -> "DeltaProposal | None":
    """Parse one `tool_calls[i].function.arguments` value (already-decoded dict OR a JSON string)
    into a validated DeltaProposal, or None if nothing recoverable is in it — never raises.

    Applies the SAME recovery `stream_chat` already relies on for this exact failure class (see
    `_extract_json_values`'s docstring for the live repros this responds to): a JSONDecodeError may
    still hide one or more complete JSON values (a valid payload followed by trailing junk, or a
    model that second-guessed itself and emitted an abandoned draft immediately followed by a
    complete, correctly-shaped proposal, both inside the same arguments string) — in which case the
    LAST candidate that actually validates against DeltaProposal wins, not just the first complete
    value found. A dict/str that parses fine but fails DeltaProposal validation (a stale or
    wrongly-shaped duplicate) also returns None here rather than raising, so the caller can keep
    looking at later tool_calls entries instead of hard-failing on one bad one."""
    if not isinstance(args, str):
        try:
            return DeltaProposal.model_validate(args)
        except Exception:
            return None
    try:
        parsed = json.loads(args)
    except json.JSONDecodeError:
        recovered = None
        for candidate, _ in reversed(_extract_json_values(args)):
            try:
                recovered = DeltaProposal.model_validate(candidate)
            except Exception:
                continue
            break
        return recovered
    try:
        return DeltaProposal.model_validate(parsed)
    except Exception:
        return None


class OpenRouterDeltaProvider(LLMProvider):
    def __init__(self, *, model: str | None = None, api_key: str | None = None,
                 base_url: str | None = None, max_tokens: int = 1024,
                 chat_max_tokens: int = _DEFAULT_CHAT_MAX_TOKENS, post=None, stream_post=None,
                 sleep=None) -> None:
        self.model = model or os.environ.get("OPENROUTER_MODEL", _DEFAULT_MODEL)
        self.api_key = api_key if api_key is not None else os.environ.get("OPENROUTER_API_KEY", "")
        self.base_url = base_url or os.environ.get("OPENROUTER_BASE_URL", _DEFAULT_BASE)
        self.max_tokens = max_tokens              # propose_delta (single-shot delta-emitter) cap
        self.chat_max_tokens = chat_max_tokens     # stream_chat (conversational) cap — see default above
        self._post = post  # injectable (url=, headers=, json=) -> dict, for tests
        self._stream_post = stream_post  # injectable (url=, headers=, json=) -> iterator[chunk dict]
        self._sleep = sleep or time.sleep  # injectable, so retry-backoff tests don't really sleep

    def _do_post(self, url: str, headers: dict, payload: dict) -> dict:
        if self._post is not None:
            return self._post(url=url, headers=headers, json=payload)
        import httpx
        resp = httpx.post(url, headers=headers, json=payload, timeout=60.0)
        resp.raise_for_status()
        return resp.json()

    def _do_post_with_retry(self, url: str, headers: dict, payload: dict) -> dict:
        """`_do_post`, bounded-retried (2 to 3 attempts total, exponential backoff) — propose_delta's
        own transport wrapper. See `_PROPOSE_DELTA_RETRY_ATTEMPTS`'s docstring for why this is scoped
        to propose_delta and not shared with judge_image or stream_chat's own `_do_stream`."""
        delay = _PROPOSE_DELTA_RETRY_BASE_DELAY_S
        last_exc: Exception | None = None
        for attempt in range(_PROPOSE_DELTA_RETRY_ATTEMPTS):
            try:
                return self._do_post(url, headers, payload)
            except Exception as e:
                if not _is_retryable_transport_error(e) or attempt == _PROPOSE_DELTA_RETRY_ATTEMPTS - 1:
                    raise
                logger.warning("propose_delta: retryable transport error on attempt %d/%d (%s) — "
                                "backing off %.2fs before retrying", attempt + 1,
                                _PROPOSE_DELTA_RETRY_ATTEMPTS, e, delay)
                last_exc = e
                self._sleep(delay)
                delay *= 2
        raise last_exc  # pragma: no cover — loop above always returns or re-raises first

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
        data = self._do_post_with_retry(f"{self.base_url}/chat/completions", headers, payload)

        message = (data.get("choices") or [{}])[0].get("message", {}) or {}
        # A forced tool_choice should mean exactly one matching tool_calls entry, but a model can
        # still double-emit (2026-07-19/23 live repros on stream_chat's identical failure class, see
        # _extract_json_values/_recover_tool_call_proposal above) — duplicate entries, an abandoned
        # draft ahead of the real proposal, or valid JSON with trailing junk. Walk every matching
        # entry and keep the LAST one that actually recovers/validates rather than blindly returning
        # the first — an earlier stale or malformed entry must not shadow a later good one.
        proposal: DeltaProposal | None = None
        for call in message.get("tool_calls") or []:
            fn = call.get("function", {})
            if fn.get("name") != _FN_NAME:
                continue
            candidate = _recover_tool_call_proposal(fn.get("arguments"))
            if candidate is not None:
                proposal = candidate
        if proposal is not None:
            return proposal
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

    def _stream_round(self, headers: dict, payload: dict, out: dict):
        """Stream ONE chat-completion request, yielding ('token', text) live as it arrives.
        Populates `out['tool_calls']` (`{index: {"id", "name", "arguments"}}`, arguments
        concatenated across fragments) and `out['finish_reason']` as a side effect once the stream
        ends — a generator's own `return` value is awkward to retrieve through a driving `for`
        loop, so this side-channel dict is simpler than threading one through. A tool call's `id`/
        `name` typically only rides on its FIRST delta fragment (subsequent fragments carry only
        more `arguments`) — captured once and kept, never overwritten by a later blank one."""
        tool_calls: dict[int, dict] = {}
        finish_reason: str | None = None
        for chunk in self._do_stream(f"{self.base_url}/chat/completions", headers, payload):
            choices = chunk.get("choices") or []
            if not choices:
                continue
            choice = choices[0]
            delta = choice.get("delta") or {}
            if delta.get("content"):
                yield ("token", delta["content"])
            for tc in delta.get("tool_calls") or []:
                idx = tc.get("index", 0)
                entry = tool_calls.setdefault(idx, {"id": None, "name": None, "arguments": ""})
                if tc.get("id"):
                    entry["id"] = tc["id"]
                fn = tc.get("function") or {}
                if fn.get("name"):
                    entry["name"] = fn["name"]
                entry["arguments"] += fn.get("arguments") or ""
            # some providers report finish_reason only on the final (often content-less) chunk —
            # keep the last non-null one seen, rather than requiring it ride with content/tool_calls.
            fr = choice.get("finish_reason")
            if fr:
                finish_reason = fr
        out["tool_calls"] = tool_calls
        out["finish_reason"] = finish_reason

    def _execute_research(self, arguments: str) -> "ResearchFinding | None":
        """Parse one `research_reference` tool call's arguments and run it through the configured
        provider. Malformed JSON just drops the call (returns None, same as an inconclusive
        lookup) — `ResearchQuery` is a single required string field, not worth the multi-candidate
        JSON recovery machinery `_recover_tool_call_proposal` needs for the much larger
        `DeltaProposal` schema. Never raises — mirrors every other provider call in this file that
        must never fabricate a result out of a broken response."""
        try:
            query = ResearchQuery.model_validate_json(arguments)
        except Exception:
            return None
        return get_research_provider().research(query.query)

    def stream_chat(self, *, messages: list[dict], ledger_json: str):
        """Yield ('token', text), ('research', ResearchFinding) — at most once per research tool
        call, only when a vendor is configured — then ('proposal', DeltaProposal), then
        ('done', None) — or ('error', msg). The model produces prose AND an optional
        propose_parameter_delta call.

        Runs a BOUNDED (`_MAX_RESEARCH_ROUNDS`) multi-round tool loop (2026-08-01) — the first
        genuinely agentic loop in this codebase (a tool result fed back into a second completion
        request), replacing a deterministic pre-turn heuristic that used to decide research
        unconditionally, with no model judgment at all. If the model calls `research_reference`
        ALONE (no propose_parameter_delta in the same round), the result is fed back as a tool
        message and the model gets ONE more completion to actually use it. If it calls BOTH in the
        same round, that round is treated as final — propose_parameter_delta is self-contained (the
        model already decided without waiting), and it has no natural "tool result" to feed back
        anyway: it's applied CLIENT-side, asynchronously, long after this response finishes, so it
        must never be the reason this loop tries to continue. The conversation built for a
        continuation round is entirely EPHEMERAL to this one call — `Chat.tsx` already collapses
        every historical turn back into plain `{role, content}` text before resending, so these raw
        assistant/tool-call/tool-result messages never need to stay protocol-valid across separate
        `/chat` requests, only within this one.

        Never silently empty end-to-end (see FIX 1 in the investigation this responds to): a
        malformed tool-call JSON, a truncated completion, or a turn that produced neither prose nor
        a usable proposal all yield an explicit ('error', ...) before the final ('done', None) —
        never just a bare done with nothing else."""
        if not self.api_key and self._stream_post is None:
            yield ("error", "OPENROUTER_API_KEY is not set")
            return
        tools = [{"type": "function", "function": {
            "name": _FN_NAME, "description": "Emit parameter deltas or request clarification.",
            "parameters": parameter_delta_tool_schema()}}]
        if research_provider_configured():
            tools.append({"type": "function", "function": {
                "name": _RESEARCH_FN_NAME,
                "description": (
                    "Look up brief reference material (a description + possibly images) for a "
                    "real-world object or mechanism, to ground which catalog part types to use "
                    "when decomposing a NEW compound design. Call this ALONE (no "
                    "propose_parameter_delta in the same turn) when you want to see the result "
                    "before deciding what to build — it comes back as a tool result and you get "
                    "one more turn to use it."),
                "parameters": research_tool_schema()}})
        stable_prompt = build_system_prompt_from_json(ledger_json)
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        conversation = list(messages)
        tool_args: dict[int, str] = {}
        saw_token = False
        finish_reason: str | None = None
        for round_num in range(_MAX_RESEARCH_ROUNDS):
            payload = {
                "model": self.model, "max_tokens": self.chat_max_tokens, "stream": True,
                "messages": [{"role": "system",
                               "content": f"{stable_prompt}\n\n## Current ledger\n{ledger_json}"}]
                            + conversation,
                "tools": tools, "tool_choice": "auto",
            }
            out: dict = {}
            try:
                for kind, text in self._stream_round(headers, payload, out):
                    saw_token = True
                    yield ("token", text)
            except Exception as e:  # network / bad key / stream error
                yield ("error", str(e))
                yield ("done", None)  # keep the ('error', ...) then ('done', None) contract even here
                return
            round_tool_calls: dict[int, dict] = out["tool_calls"]
            if out["finish_reason"]:
                finish_reason = out["finish_reason"]
            research_calls = [tc for tc in round_tool_calls.values()
                               if (tc["name"] or _FN_NAME) == _RESEARCH_FN_NAME]
            propose_calls = {idx: tc["arguments"] for idx, tc in round_tool_calls.items()
                              if (tc["name"] or _FN_NAME) == _FN_NAME}
            tool_result_messages = []
            for tc in research_calls:
                finding = self._execute_research(tc["arguments"])
                if finding is not None:
                    yield ("research", finding)
                tool_result_messages.append({
                    "role": "tool", "tool_call_id": tc["id"],
                    "content": json.dumps(finding.model_dump(mode="json") if finding is not None
                                           else {"note": "no reference results found for this query"}),
                })
            tool_args = propose_calls  # this round's propose calls are authoritative either way
            more_rounds_allowed = round_num < _MAX_RESEARCH_ROUNDS - 1
            if research_calls and not propose_calls and more_rounds_allowed:
                assistant_tool_calls = [
                    {"id": tc["id"], "type": "function",
                     "function": {"name": tc["name"] or _RESEARCH_FN_NAME, "arguments": tc["arguments"]}}
                    for tc in research_calls
                ]
                conversation = conversation + [
                    {"role": "assistant", "content": None, "tool_calls": assistant_tool_calls},
                    *tool_result_messages,
                ]
                continue
            break
        saw_proposal = False
        # Tracks whether a SPECIFIC per-tool-call error was already yielded (a parse failure or a
        # schema-validation failure, neither one truncation-shaped) — see the end-of-stream check
        # below for why this must suppress the generic "no response was generated" fallback.
        yielded_specific_error = False
        # A completion cut off by the max_tokens cap ("length") already fully explains a malformed
        # trailing tool-call arg string; the generic parse-failure message is redundant noise on top
        # of the more specific, more actionable "cut off" message a few lines down, and it's the
        # WRONG suggestion ("try rephrasing") for what's actually a "the reply was too big" problem
        # (2026-07-19 live repro: a multi-part build request truncated mid-tool-call-JSON, and the
        # user only needed to know to try a smaller request, not that "parsing failed").
        #
        # finish_reason ALONE is not reliable for DETECTING a cutoff (a second live repro, same
        # session: the raw stream never surfaced finish_reason=="length" for an OpenRouter/DeepSeek
        # tool-call stream that was, by every other signal, truncated — the misleading message still
        # showed). Detect a missed cutoff from the JSON failure itself instead — see
        # _looks_truncated's own docstring for why pos alone isn't enough (an "Unterminated string"
        # error's pos points at the string's OPENING quote, not where the stream actually ran out, so
        # it can sit far from len(args) even when truncation is exactly what happened).
        #
        # It is ALSO not reliable in the OPPOSITE direction (found 2026-07-21, live-reproduced below):
        # OpenRouter proxies many backend models, each free to report its own terminal-state string:
        # `{"stop", "tool_calls"}` are the two ROUTINE OpenAI-compatible reasons for "finished
        # normally, nothing missing" — anything else this code had never seen before (a model that
        # says "eos", a proxy quirk, a legacy "function_call") got blanket-treated as truncation, even
        # when every tool call in the response went on to parse AND validate cleanly. That produced a
        # genuine self-contradiction: a fully successful, fully-applied proposal (real geometry
        # already mutated) landing next to "the response was cut off before finishing — try a shorter
        # or simpler request" in the SAME chat turn — confusing at best, and an invitation to retry an
        # already-applied edit at worst. "length"/"content_filter" are UNAMBIGUOUS, well-known
        # OpenAI-compatible signals that content is genuinely missing beyond what streamed, so those
        # must still override even a successfully-parsed proposal (test:
        # test_stream_chat_truncated_finish_reason_yields_error) — only a truly UNRECOGNIZED reason
        # gets the benefit of the doubt once a proposal actually validates.
        _KNOWN_TRUNCATION_REASONS = frozenset({"length", "content_filter"})
        _KNOWN_COMPLETE_REASONS = frozenset({None, "stop", "tool_calls", "function_call"})
        truncated = finish_reason in _KNOWN_TRUNCATION_REASONS
        finish_reason_unrecognized = (
            finish_reason not in _KNOWN_TRUNCATION_REASONS and finish_reason not in _KNOWN_COMPLETE_REASONS
        )
        for args in tool_args.values():
            try:
                parsed = json.loads(args)
            except json.JSONDecodeError as e:
                # Recovery: some streams append content AFTER a complete, valid top-level JSON value
                # (2026-07-19 live repro — "Extra data: line 2 column 1 (char 10086)" on a 10121-char
                # args string: a fully valid ~10KB tool call followed by ~35 bytes of something else,
                # finish_reason=="tool_calls" — a NORMAL completion, not a cutoff). json.loads demands
                # the WHOLE string be one JSON value and throws the real proposal away over transport
                # noise appended after it. genuinely malformed JSON (a missing value, an unterminated
                # string, a syntax error INSIDE the structure) yields zero extracted values, identical
                # to the old single-raw_decode behavior — so this can only ever help a "valid value(s)
                # + trailing junk" case, never mask a real parse failure or a genuine truncation, and
                # _looks_truncated below is unaffected.
                values = _extract_json_values(args)
                recovered, leftover = None, None
                if values:
                    # Prefer the LAST candidate that actually validates, not just the first complete
                    # value found (2026-07-23 live repro: a model emitted an abandoned, wrongly-shaped
                    # draft FIRST, then a complete correctly-shaped proposal second, both inside one
                    # tool call — picking "first complete value" silently kept the bad draft and threw
                    # away the good one as "trailing junk"). Falls back to the first value (old
                    # behavior) if nothing validates, so schema-invalidation still reports normally.
                    recovered = values[0][0]
                    for candidate, _ in reversed(values):
                        try:
                            DeltaProposal.model_validate(candidate)
                        except Exception:
                            continue
                        recovered = candidate
                        break
                    leftover = values[-1][1]
                if recovered is not None:
                    logger.warning("stream_chat: recovered a tool-call payload out of %d complete JSON "
                                   "value(s); ignored %d bytes of trailing data (finish_reason=%r): %r",
                                   len(values), len(leftover), finish_reason, leftover[:200])
                    parsed = recovered
                else:
                    # finish_reason + len(args) alongside the parse error itself (2026-07-19 live
                    # repro: a "cut off" classification fired on an args string of only ~900 chars,
                    # nowhere near chat_max_tokens — logging just the parse error left no way to tell
                    # "genuinely hit the token cap" apart from "the stream ended early for some other
                    # reason" after the fact).
                    logger.warning("stream_chat: failed to parse tool-call arguments (%s) "
                                   "[finish_reason=%r, len(args)=%d]", e, finish_reason, len(args))
                    if _looks_truncated(args, e):
                        truncated = True
                    elif not truncated:
                        yield ("error", "the model's proposal could not be parsed — try rephrasing or asking again")
                        yielded_specific_error = True
                    continue
            try:
                proposal = DeltaProposal.model_validate(parsed)
            except Exception as e:
                # valid JSON that doesn't match the DeltaProposal schema — a genuinely different
                # failure than truncation (the syntax was complete), so the position heuristic above
                # doesn't apply; still worth a signal rather than the old silent `continue`.
                logger.warning("stream_chat: tool-call arguments failed schema validation (%s)", e)
                logger.warning("STREAM_DEBUG full parsed payload: %r", parsed)  # TEMP — remove after live capture
                if not truncated:
                    yield ("error", "the model's proposal could not be parsed — try rephrasing or asking again")
                    yielded_specific_error = True
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
        if truncated or (finish_reason_unrecognized and not saw_proposal):
            # e.g. "length" — cut off by the max_tokens cap; "content_filter" etc. also land here. An
            # unrecognized finish_reason with NO successful proposal falls back to the same message
            # (still the safest guess when nothing usable came through) — but NOT when a proposal
            # already validated: that's direct, positive evidence the completion was actually fine.
            yield ("error", "the response was cut off before finishing — try a shorter or simpler request")
        elif not saw_token and not saw_proposal and not yielded_specific_error:
            # "no response was generated" would be actively wrong here if truncated: something WAS
            # generated, it just didn't survive parsing — the "cut off" message above already covers
            # that case with the correct explanation, so this one only applies when nothing was cut
            # off either (a genuinely empty/no-op turn). It is ALSO wrong — and, before this fix,
            # ACTUALLY FIRED (2026-07-21, live-reproduced: a single malformed/schema-invalid tool call
            # with no finish_reason-based truncation signal) — when a specific per-tool-call error was
            # already yielded above: that message already told the user exactly what went wrong ("the
            # model's proposal could not be parsed"), so stacking a second, more generic "no response
            # was generated" underneath it is pure redundant noise, not new information, in the SAME
            # contradictory-pair-of-messages shape every other fix in this function already guards
            # against. Only fire this generic backstop when NOTHING at all was communicated yet.
            yield ("error", "no response was generated for that message — try rephrasing or asking again")
        yield ("done", None)

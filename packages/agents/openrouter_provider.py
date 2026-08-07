"""OpenRouter delta-emitter (OpenAI-compatible) — the hosted LLM seam impl. Default model: DeepSeek.

Vendor-agnostic on purpose: OpenRouter exposes an OpenAI-style /chat/completions with function-calling,
so we bind the model to the `propose_parameter_delta` function with forced `tool_choice` — its only
possible output is a validated `DeltaProposal` (no prose, no free Python, no safety scalar).

Config (the "input field"): `OPENROUTER_API_KEY` and optional `OPENROUTER_MODEL` env vars (see
`.env.example`), or pass them to the constructor. Implemented over httpx (no vendor SDK); a `post`
callable can be injected for tests so this is exercised with no key / no network.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import time

from packages.agents.custom_geometry_provider import (
    GeneratedSubsystemCandidateArgs,
    custom_geometry_enabled,
    custom_geometry_tool_schema,
)
from packages.agents.llm_provider import LLMProvider
from packages.agents.prompt_builder import build_system_prompt_from_json
from packages.agents.read_subsystem_provider import (
    SubsystemSourceQuery,
    read_subsystem_source,
    read_subsystem_source_enabled,
    read_subsystem_source_tool_schema,
)
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
# The model's OWN decision to read an EXISTING catalog subsystem's real build123d source before
# writing/deciding something new (Phase 4, 2026-08-06) — see read_subsystem_provider.py's module
# docstring. Offered as a further tool ALONGSIDE _FN_NAME (and _RESEARCH_FN_NAME, when configured)
# whenever read_subsystem_source_enabled() is true (default-on — see that function's own docstring).
_READ_SUBSYSTEM_SOURCE_FN_NAME = "read_subsystem_source"
# The model's OWN decision to write genuinely NEW build123d geometry as a permanent catalog subsystem,
# via Phase 3's registration gate (Phase 5, 2026-08-06) — see custom_geometry_provider.py's module
# docstring. Offered as a further tool ALONGSIDE the others whenever custom_geometry_enabled() is true
# (default-OFF — unlike read_subsystem_source, this has real write/registration consequences).
_CUSTOM_GEOMETRY_FN_NAME = "propose_custom_geometry"
# 1 initial completion + up to 3 continuation rounds once the model has a tool result in hand — a hard
# cap, not configurable, so a model that keeps calling continuation-shaped tools can never turn one
# chat turn into an unbounded chain of completion requests. Raised from 2 (1 initial + 1 continuation,
# enough for research_reference alone) to 4 on 2026-08-06 when read_subsystem_source landed alongside
# it: a realistic "read source, then decide" turn only needs 2, but this is sized for the FOUR-step
# sequence propose_custom_geometry (Phase 5) realistically needs — read reference source, generate an
# attempt, react to a build failure, retry once — not padded any further than that named sequence
# actually requires.
_MAX_TOOL_ROUNDS = 4
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


def _strict_schema(schema: dict) -> dict:
    """Deep-copy `schema` (a pydantic v2 `model_json_schema()` output, e.g.
    `parameter_delta_tool_schema()`) into an OpenAI `"strict": true`-compatible shape: every
    object-shaped node (any dict with a "properties" key) gets `"required"` set to the FULL, sorted
    list of its own property names, and `"additionalProperties"` set to `False`. Never mutates the
    caller's dict.

    This is a mechanical transform, not a schema rewrite: pydantic v2 already emits the exact shape
    strict mode wants for an `Optional[X] = None` field (`"anyOf": [{"type": "X"}, {"type":
    "null"}], "default": null`) — the ONLY gap is that OpenAI strict mode additionally requires
    every property to be listed in "required" (nullable or not), which pydantic does not do for
    optional fields. "default"/enum lists/"title"/"description"/"type" are left exactly as-is.

    Recurses through every place `model_json_schema()` actually nests another schema: "$defs" (one
    entry per referenced model), "properties" (each field's own schema), "items" (array element
    schema), and "anyOf"/"oneOf"/"allOf" (union branches, e.g. an Optional[SomeModel] field or an
    enum-typed field). A `$defs` entry with no "properties" (e.g. a bare enum like `LockState`) is
    left untouched, as intended — only object nodes get "required"/"additionalProperties"."""
    schema = copy.deepcopy(schema)

    def walk(node) -> None:
        if not isinstance(node, dict):
            return
        if isinstance(node.get("properties"), dict):
            node["required"] = sorted(node["properties"].keys())
            node["additionalProperties"] = False
            for prop_schema in node["properties"].values():
                walk(prop_schema)
        if isinstance(node.get("$defs"), dict):
            for def_schema in node["$defs"].values():
                walk(def_schema)
        if "items" in node:
            walk(node["items"])
        for key in ("anyOf", "oneOf", "allOf"):
            for branch in node.get(key) or []:
                walk(branch)

    walk(schema)
    return schema


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


def _is_strict_schema_rejection(e: Exception) -> bool:
    """True for a 4xx OTHER than 429 — the shape a provider/model uses to reject a request it didn't
    like the STRUCTURE of (e.g. an unsupported `"strict": true` tool schema), as distinct from a
    transient transport failure. Used to decide whether falling back to a DIFFERENT, known-plain
    tool schema is worth a retry — narrowly, NOT a general "retry on 4xx" policy (a genuinely bad
    request — bad model name, malformed conversation — is still propagated immediately, unchanged
    from the long-standing non-retryable-4xx contract this file already has).

    429 is excluded even though it is itself a 4xx: it's a rate limit, not a schema complaint, and a
    different schema shape cannot fix "too many requests" — falling back here would just be a wasted
    extra attempt on top of `_do_post_with_retry`'s own already-exhausted retry budget for it. Every
    5xx/timeout is excluded for the same reason: those failure classes have nothing to do with
    strict-schema support either."""
    status = getattr(getattr(e, "response", None), "status_code", None)
    return isinstance(status, int) and 400 <= status < 500 and status != 429


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


# -- model capability lookup (vision-in-the-loop, 2026-08-05) ---------------------------------------
# OpenRouter's PUBLIC model registry (no auth needed) is the only ground truth for "can THIS model id
# see an image" -- a hard-coded allowlist of vision-capable model ids would silently go stale the
# moment a new model ships or an existing one's modalities change. Cached at module level (a plain
# (models, fetched_at) tuple -- no lock, no distributed cache: this project's established "wedge
# simplicity" bar) so a capability check isn't a network round-trip on every call.
_MODEL_REGISTRY_URL = f"{_DEFAULT_BASE}/models"
_MODEL_REGISTRY_CACHE_TTL_S = 3600.0  # 1 hour
_model_registry_cache: "tuple[list, float] | None" = None  # (models, fetched_at) -- see _fetch_model_registry


def _fetch_model_registry(get) -> list:
    """Return OpenRouter's `GET /models` response's `"data"` array -- from the module-level cache if
    a fetch within `_MODEL_REGISTRY_CACHE_TTL_S` already succeeded, else a fresh fetch. The cache is
    updated ONLY on a successful fetch -- a transient failure must never poison it for the rest of the
    TTL window (the next call should get a fresh chance, not a cached failure). Raises on any failure
    (network error, non-dict response, missing/non-list "data"); `model_supports_vision` (the one
    caller) is what turns that into a safe False.

    `get` mirrors `OpenRouterDeltaProvider._post`'s own constructor-injection pattern: an injectable
    `(url=...) -> dict` callable for tests, defaulting to a real (unauthenticated -- this endpoint
    needs no API key) `httpx.get` when not injected."""
    global _model_registry_cache
    now = time.time()
    if _model_registry_cache is not None and now - _model_registry_cache[1] < _MODEL_REGISTRY_CACHE_TTL_S:
        return _model_registry_cache[0]
    if get is not None:
        data = get(url=_MODEL_REGISTRY_URL)
    else:
        import httpx
        resp = httpx.get(_MODEL_REGISTRY_URL, timeout=10.0)
        resp.raise_for_status()
        data = resp.json()
    models = data["data"]
    if not isinstance(models, list):
        raise ValueError("malformed OpenRouter /models response: 'data' is not a list")
    _model_registry_cache = (models, now)
    return models


def model_supports_vision(model: str, *, get=None) -> bool:
    """True iff OpenRouter's public model registry lists `model`'s own entry with "image" in its
    `architecture.input_modalities`. Returns False -- NEVER raises -- for an unknown/absent model id,
    a network failure, or a malformed response: a missing/uncertain capability must never be treated
    as "yes" (same defensive posture as `vision_model_configured()`/`validate_visual()` in
    `vision_validator.py` -- a fabricated "this model can see" is exactly the kind of confident-wrong
    green light this codebase's whole safety posture exists to prevent).

    See `_fetch_model_registry` for the injectable `get` / caching contract."""
    if not model:
        return False
    try:
        models = _fetch_model_registry(get)
        for m in models:
            if isinstance(m, dict) and m.get("id") == model:
                arch = m.get("architecture")
                modalities = arch.get("input_modalities") if isinstance(arch, dict) else None
                return isinstance(modalities, list) and "image" in modalities
        return False
    except Exception as e:
        logger.warning("model_supports_vision: could not resolve vision capability for %r (%s)", model, e)
        return False


def _last_user_message_text(conversation: list[dict]) -> str:
    """The most recent `{"role": "user", ...}` entry's own text content in `conversation`, or `""` if
    none — used as `GeneratedSubsystemCandidate.user_request_excerpt` context for a
    `propose_custom_geometry` call (Phase 5), so a later human reviewer of the generation-attempt
    corpus can see what the user actually asked for. `content` is usually a plain string, but a
    vision-in-the-loop turn (`judge_image`'s own content-list shape) can carry a list of `{"type",
    "text"/"image_url"}` parts instead — only the text parts are joined; an image part contributes
    nothing here (there is no text to excerpt from it). Never raises: a malformed/unexpected
    `content` shape just falls through to `""`, same as "no user message found" — this is context for
    a human review field, not something worth failing a registration attempt over.

    Deliberately does NOT truncate — `GenerationAttempt.user_request_excerpt`'s own field validator
    (`packages/truth_plane/generated_subsystem_store.py`) already caps this at
    `MAX_REQUEST_EXCERPT_CHARS`; re-implementing that cap here would just be a second, possibly
    inconsistent source of truth for the same limit."""
    for msg in reversed(conversation):
        if not isinstance(msg, dict) or msg.get("role") != "user":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return " ".join(
                part.get("text", "") for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            )
        return ""
    return ""


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

        description = "Emit parameter deltas or request clarification."
        plain_schema = parameter_delta_tool_schema()
        plain_tool = {"type": "function", "function": {
            "name": _FN_NAME, "description": description, "parameters": plain_schema}}
        strict_tool = {"type": "function", "function": {
            "name": _FN_NAME, "description": description,
            "parameters": _strict_schema(plain_schema), "strict": True}}
        messages = ([{"role": "system", "content": system or _SYSTEM}] + conversation
                    + [{"role": "user", "content": f"Current ledger: {ledger_json}"}])
        tool_choice = {"type": "function", "function": {"name": _FN_NAME}}
        strict_payload = {
            "model": self.model, "max_tokens": self.max_tokens, "messages": messages,
            "tools": [strict_tool], "tool_choice": tool_choice,
        }
        plain_payload = {
            "model": self.model, "max_tokens": self.max_tokens, "messages": messages,
            "tools": [plain_tool], "tool_choice": tool_choice,
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        url = f"{self.base_url}/chat/completions"
        # Bind to `parameter_delta_tool_schema()` under a strict, grammar-constrained tool schema
        # first (2026-08-04 — eliminates the "dropped comma in a large free-generated JSON blob"
        # failure class BY CONSTRUCTION, live-reproduced: `stream_chat: failed to parse tool-call
        # arguments (Expecting ',' delimiter...)` on a syntactically-complete, non-truncated
        # completion). Not every OpenRouter model/provider supports `"strict": true` though — the
        # Settings modal lets a user type ANY model string — so a schema-shaped 400 gets exactly ONE
        # retry against a known-plain (today's original, unconstrained) schema; any other failure
        # (429, 5xx, timeout, or a genuinely bad 400 unrelated to schema support) propagates exactly
        # as it always has, with no fallback.
        try:
            data = self._do_post_with_retry(url, headers, strict_payload)
        except Exception as e:
            if not _is_strict_schema_rejection(e):
                raise
            logger.warning("propose_delta: strict-schema tool call rejected (%s) — retrying once "
                            "with a plain (non-strict) tool schema", e)
            data = self._do_post_with_retry(url, headers, plain_payload)

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
                except json.JSONDecodeError as e:
                    # 2026-08-04 — this used to swallow a malformed SSE event with zero trace. If this
                    # ever fires mid-tool-call, whatever `arguments` FRAGMENT lived in this event is
                    # gone for good — the two surviving fragments on either side of it get concatenated
                    # in _stream_round with nothing between them, which is EXACTLY the "Expecting ','
                    # delimiter" shape a downstream json.loads(full_args) failure has (live-reproduced:
                    # finish_reason='tool_calls', len(args) in the 11-16KB range). Logging the raw event
                    # here is what turns "the model probably generated bad JSON" from a guess into a
                    # provable answer next time this happens — if this line NEVER fires across a repro
                    # of the failure, that rules out a dropped-chunk explanation entirely.
                    logger.warning("stream_chat: dropped an unparseable SSE event (%s), %d bytes: %r",
                                   e, len(data), data[:500])
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

    def _stream_round_with_strict_fallback(self, headers: dict, strict_payload: dict, plain_payload: dict,
                                            out: dict):
        """`_stream_round`, with the SAME strict-schema-rejection fallback `propose_delta` gets (see
        `_is_strict_schema_rejection`) — applied to ONE streaming round instead of a single POST.
        Yields every ('token', text) item from the strict attempt AS IT ARRIVES (live, not
        buffered), tracking whether anything was yielded yet this round.

        Falls back to a FRESH `_stream_round(headers, plain_payload, out)` ONLY when the strict
        attempt raises BEFORE yielding anything this round, AND the exception is a genuine
        strict-schema rejection (not a transport failure, not 429 — see `_is_strict_schema_rejection`
        for why those are excluded). Once even one token has streamed, the provider already accepted
        the strict request and started generating — switching schemas mid-stream would be incoherent,
        and there is no way to un-yield tokens already handed to the caller — so anything yielded, or
        any non-matching exception, re-raises immediately instead.

        The plain retry is deliberately NOT wrapped in another fallback layer of its own: if it also
        fails, that exception propagates unchanged, exactly like `propose_delta`'s single fallback
        attempt — `stream_chat`'s own `except Exception as e: yield ("error", str(e)); yield
        ("done", None); return` around this call is what turns it into the normal error contract,
        untouched by this method."""
        yielded_anything = False
        try:
            for item in self._stream_round(headers, strict_payload, out):
                yielded_anything = True
                yield item
        except Exception as e:
            if yielded_anything or not _is_strict_schema_rejection(e):
                raise
            logger.warning("stream_chat: strict-schema tool call rejected before this round produced "
                            "anything (%s) — retrying this round once with a plain (non-strict) tool "
                            "schema", e)
            yield from self._stream_round(headers, plain_payload, out)

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

    def _execute_read_subsystem_source(self, arguments: str) -> str:
        """Parse one `read_subsystem_source` tool call's arguments and resolve the named subsystem's
        real source via `read_subsystem_provider.read_subsystem_source` — same shape as
        `_execute_research` just above, one required string field, no multi-candidate JSON recovery
        needed. Malformed JSON here is a genuinely different failure than an unknown subsystem name
        (that one already gets its own clear "not found" string from `read_subsystem_source` itself)
        — it means the tool CALL itself was malformed, so it gets its own clear string rather than
        silently dropping the call the way `_execute_research` drops to `None` (there is no
        "inconclusive" state here worth threading through the dispatch below — every continuation
        tool result here is always a concrete string). Never raises."""
        try:
            query = SubsystemSourceQuery.model_validate_json(arguments)
        except Exception:
            return "The subsystem name argument for this tool call could not be parsed."
        return read_subsystem_source(query.subsystem_name)

    def _execute_custom_geometry(
        self, arguments: str, *, project_id: str | None, user_request_excerpt: str,
        store=None, generated_dir=None,
    ) -> "object":
        """Parse one `propose_custom_geometry` tool call's arguments and run it through Phase 3's
        registration gate (`register_generated_subsystem`). NEVER raises — malformed JSON (or JSON
        that doesn't match `GeneratedSubsystemCandidateArgs`, e.g. a model that tried to smuggle a
        caller-supplied `model`/`project_id` field into its own tool-call JSON — see
        `custom_geometry_provider.py`'s module docstring) becomes a rejected-with-clear-reason
        `RegistrationResult`-shaped response instead, same "never raise" contract every other handler
        in this file already follows (see `_execute_read_subsystem_source` for the identical
        malformed-JSON pattern this mirrors).

        `project_id` is `stream_chat`'s own optional parameter — `None` (any caller that hasn't
        started passing a real one yet) is handled explicitly here, never propagated as a literal
        `"None"` string, matching `GeneratedSubsystemCandidate.project_id`'s own plain `str` type.
        `store`/`generated_dir` are test-only passthroughs (mirror Phase 3's own
        `register_generated_subsystem(store=..., generated_dir=...)` test-injection knobs exactly —
        see `generated_registration.py`'s own test suite) — both default to the real thing
        (`generation_attempt_store_from_env()` / `packages/subsystems/generated/`) when not supplied,
        so no production call site ever needs to pass either.

        Deliberately calls `register_generated_subsystem()` with NO `event_log` — this provider stays
        ledger-agnostic (it doesn't own a project's `EventLog`); the per-project ledger pointer append
        is `packages/transport/app.py`'s `/chat` route's own responsibility, the one place that
        actually has `state.log` in scope — see this module's own imports (no `packages.ledger.events`
        beyond what `DeltaProposal` already needs) and `generated_registration.py`'s own module
        docstring for why `event_log` is optional on `register_generated_subsystem` in the first
        place."""
        # Lazy import (mirrors `_execute_read_subsystem_source`'s own `from packages.subsystems import
        # get_subsystem_model` inside the function body, not at module top): `generated_registration`
        # transitively pulls in `packages.subsystems` and `packages.truth_plane`, both far heavier than
        # anything else this file needs at import time, and this codebase's established convention
        # (read_subsystem_provider.py) is to keep that weight out of the module-level import graph.
        from packages.subsystems.generated_registration import (
            GeneratedParamSpec, GeneratedSubsystemCandidate, RegistrationResult,
            register_generated_subsystem,
        )
        from packages.truth_plane.generated_subsystem_store import generation_attempt_store_from_env

        try:
            args = GeneratedSubsystemCandidateArgs.model_validate_json(arguments)
        except Exception as e:
            return RegistrationResult(
                accepted=False, outcome="rejected", subsystem_name="", attempt_id="",
                rejected_floor="malformed_tool_call",
                rejection_reason=(
                    f"the propose_custom_geometry tool call arguments could not be parsed: {e}"),
                model=self.model,
            )
        candidate = GeneratedSubsystemCandidate(
            subsystem_name=args.subsystem_name,
            description=args.description,
            build_code=args.build_code,
            params=[GeneratedParamSpec(**p.model_dump()) for p in args.params],
            model=self.model,
            project_id=project_id or "",
            user_request_excerpt=user_request_excerpt,
        )
        resolved_store = store if store is not None else generation_attempt_store_from_env()
        return register_generated_subsystem(
            candidate, store=resolved_store, generated_dir=generated_dir)

    def _handle_custom_geometry_tool_call(
        self, arguments: str, *, project_id: str | None = None, user_request_excerpt: str = "",
    ) -> "tuple[dict, tuple[str, object] | None]":
        """`propose_custom_geometry`'s own continuation-dispatch handler — same 1-arg dispatch shape
        as `_handle_research_tool_call`/`_handle_read_subsystem_source_tool_call` when called with
        just `arguments` (both keyword-only extras default so this method itself satisfies that
        signature), but it needs CALL-SCOPED context (`project_id`, the user's own most recent
        message) those two don't — `stream_chat` registers a small closure over THIS method (built
        inside `stream_chat` itself, capturing `project_id`/`conversation` — see the "CALL-SCOPED
        CONTEXT" note on the dispatch block below) as the actual `continuation_handlers` entry, never
        this method directly.

        Returns a small JSON-serializable dict (not the raw dataclass — `RegistrationResult` isn't
        JSON-serializable via plain `json.dumps` on its own) as the tool-result content fed back to the
        model, PLUS the full `RegistrationResult` in the event tuple for `stream_chat`'s own caller
        (`app.py`'s `/chat` route) to use for the real per-project ledger pointer append."""
        result = self._execute_custom_geometry(
            arguments, project_id=project_id, user_request_excerpt=user_request_excerpt)
        content = {
            "accepted": result.accepted, "outcome": result.outcome,
            "subsystem_name": result.subsystem_name,
            "rejected_floor": result.rejected_floor, "rejection_reason": result.rejection_reason,
        }
        return content, ("custom_geometry", result)

    # -- continuation-shaped tool dispatch (generalized 2026-08-06, Phase 4) --------------------
    # Each handler here takes one tool call's raw `arguments` string and returns
    # `(tool_result_content, event)`: `tool_result_content` is JSON-serialized verbatim into the
    # `{"role": "tool", ...}` message fed back to the model; `event` is an OPTIONAL `(kind, payload)`
    # pair yielded to stream_chat's own caller for live display (`research_reference` surfaces a
    # `('research', ResearchFinding)` event this way; `read_subsystem_source` has no display-worthy
    # event of its own — its source text only ever needs to reach the MODEL, not the UI — so it
    # always returns `None` here). This is the seam a LATER phase's `propose_custom_geometry`
    # continuation handler plugs into without touching the round loop itself — see
    # `stream_chat`'s own docstring for the generalized round-loop contract this feeds.
    #
    # SHARED CONTRACT, part of this dispatch shape itself (not just each handler's own docstring):
    # a handler must NEVER raise. `_execute_research` and `_execute_read_subsystem_source` each
    # already document this individually, but it applies to every entry in `continuation_handlers`,
    # including any a later phase adds (e.g. `propose_custom_geometry`'s sandboxed build, a real
    # failure mode with real ways to raise) — the dispatch loop in `stream_chat` below also catches
    # a handler that breaks this rule as defense-in-depth, but that is a coarser, generic message;
    # a well-behaved handler that reports its OWN failure as a normal tool-result string keeps the
    # specific, actionable error this file otherwise guarantees for every failure class.
    #
    # CALL-SCOPED CONTEXT BEYOND `arguments` (2026-08-06 repair — R3 CONFIRMED, low): this dispatch
    # shape is deliberately fixed at `(arguments: str) -> (dict, event|None)` and is NOT meant to grow
    # more positional parameters as later phases add handlers — that would mean touching the shared
    # `continuation_handlers[tc["name"]](tc["arguments"])` call site (and the round loop around it)
    # every time a new handler wants something extra, exactly the "second loop refactor" this
    # generalization exists to avoid. `_handle_research_tool_call` and
    # `_handle_read_subsystem_source_tool_call` are already BOUND methods — registered below as
    # `self._handle_research_tool_call`, not free functions — so `self` (and therefore `self.model`)
    # is already reachable from every handler with zero signature change. A handler that needs MORE
    # than that (conversation history, `project_id`, the user's own message — e.g. a later
    # `propose_custom_geometry` handler building a candidate, per spicy-exploring-cupcake.md Phase 5)
    # gets it the same way every other per-tool difference in this method already exists: as a
    # closure/lambda built HERE, inside `stream_chat`, at the point it's added to
    # `continuation_handlers` — mirroring the `if research_provider_configured(): ...` /
    # `if read_subsystem_source_enabled(): ...` blocks below, which already vary per-tool without
    # touching the round loop itself. `conversation` and `ledger_json` are already local to
    # `stream_chat` and closeable-over today; `project_id` was NOT — `stream_chat` never received it
    # at all — so it's now an optional `stream_chat` parameter (see its own docstring) specifically so
    # a future closure has something to capture. Nothing in THIS phase reads it; it's plumbing, not
    # behavior, and the round loop's control flow is untouched by adding it.
    def _handle_research_tool_call(self, arguments: str) -> "tuple[dict, tuple[str, object] | None]":
        finding = self._execute_research(arguments)
        if finding is not None:
            return finding.model_dump(mode="json"), ("research", finding)
        return {"note": "no reference results found for this query"}, None

    def _handle_read_subsystem_source_tool_call(self, arguments: str) -> "tuple[dict, tuple[str, object] | None]":
        return {"source": self._execute_read_subsystem_source(arguments)}, None

    def stream_chat(self, *, messages: list[dict], ledger_json: str, project_id: str | None = None):
        """Yield ('token', text), ('research', ResearchFinding) — at most once per research tool
        call, only when a vendor is configured — then ('proposal', DeltaProposal), then
        ('done', None) — or ('error', msg). The model produces prose AND an optional
        propose_parameter_delta call.

        `project_id` (2026-08-06 repair — R3 CONFIRMED, low; consumed starting Phase 5, same day) is
        optional, keyword-only, additive call-scoped context — `app.py`'s `/chat` route now passes its
        real `state.file_id` here; every OTHER existing caller (`eval_graph.py`, every `stream_chat`
        test that doesn't pass it) is unaffected by the default of `None`, handled explicitly by
        `_execute_custom_geometry` (`project_id or ""`) rather than propagated as a literal `"None"`
        string. Only `propose_custom_geometry`'s own handler reads it today (see the "CALL-SCOPED
        CONTEXT" note on the dispatch block above `_handle_research_tool_call`, and the
        `custom_geometry_enabled()` block below) — every other continuation handler still ignores it.

        Runs a BOUNDED (`_MAX_TOOL_ROUNDS`) multi-round tool loop (2026-08-01, generalized
        2026-08-06) — the first genuinely agentic loop in this codebase (a tool result fed back into
        a further completion request), replacing a deterministic pre-turn heuristic that used to
        decide research unconditionally, with no model judgment at all. Every CONTINUATION-shaped
        tool (currently `research_reference`, `read_subsystem_source`, and `propose_custom_geometry`
        — see the `continuation_handlers` dict built below, a `{tool_name: handler}` dispatch — never
        a new hardcoded branch here) works the same way: if the model calls ONE OR MORE of them ALONE
        (no `propose_parameter_delta` in the same round) and rounds remain, every result is fed back as
        its own tool message and the model gets one more completion to actually use them. If it
        calls a continuation tool AND `propose_parameter_delta` in the SAME round, that round is
        still treated as final — `propose_parameter_delta` (`_FN_NAME`) is the ONE hardcoded terminal
        tool name, completely separate from the continuation dispatch: it's self-contained (the model
        already decided without waiting) and has no natural "tool result" to feed back anyway — it's
        applied CLIENT-side, asynchronously, long after this response finishes, so it must never be
        the reason this loop tries to continue. The conversation built for a continuation round is
        entirely EPHEMERAL to this one call — `Chat.tsx` already collapses every historical turn back
        into plain `{role, content}` text before resending, so these raw assistant/tool-call/
        tool-result messages never need to stay protocol-valid across separate `/chat` requests, only
        within this one.

        Never silently empty end-to-end (see FIX 1 in the investigation this responds to): a
        malformed tool-call JSON, a truncated completion, or a turn that produced neither prose nor
        a usable proposal all yield an explicit ('error', ...) before the final ('done', None) —
        never just a bare done with nothing else."""
        if not self.api_key and self._stream_post is None:
            yield ("error", "OPENROUTER_API_KEY is not set")
            return
        # Strict/plain variants of the propose_parameter_delta tool ONLY (same fallback rationale as
        # propose_delta — see its own comment) — every CONTINUATION-shaped tool below, when offered,
        # is added UNCHANGED and identical to both lists, out of scope for this fix (much smaller
        # schemas, not implicated in the reported failure).
        description = "Emit parameter deltas or request clarification."
        plain_delta_schema = parameter_delta_tool_schema()
        plain_tools = [{"type": "function", "function": {
            "name": _FN_NAME, "description": description, "parameters": plain_delta_schema}}]
        strict_tools = [{"type": "function", "function": {
            "name": _FN_NAME, "description": description,
            "parameters": _strict_schema(plain_delta_schema), "strict": True}}]
        # {tool_name: handler} — every CONTINUATION-shaped tool actually offered this call (gated the
        # SAME way its own entry below is added to plain_tools/strict_tools). propose_parameter_delta
        # (_FN_NAME) deliberately has NO entry here — it stays the one hardcoded terminal tool name,
        # checked separately below. A later phase's propose_custom_geometry continuation handler adds
        # a third entry to this dict, never a new branch in the round loop itself.
        continuation_handlers: dict = {}
        if research_provider_configured():
            research_tool = {"type": "function", "function": {
                "name": _RESEARCH_FN_NAME,
                "description": (
                    "Look up brief reference material (a description + possibly images) for a "
                    "real-world object or mechanism, to ground which catalog part types to use "
                    "when decomposing a NEW compound design. Call this ALONE (no "
                    "propose_parameter_delta in the same turn) when you want to see the result "
                    "before deciding what to build — it comes back as a tool result and you get "
                    "one more turn to use it."),
                "parameters": research_tool_schema()}}
            plain_tools.append(research_tool)
            strict_tools.append(research_tool)
            continuation_handlers[_RESEARCH_FN_NAME] = self._handle_research_tool_call
        if read_subsystem_source_enabled():
            read_source_tool = {"type": "function", "function": {
                "name": _READ_SUBSYSTEM_SOURCE_FN_NAME,
                "description": (
                    "Read an EXISTING, already-registered catalog subsystem's own build123d source "
                    "code as a concrete reference before writing or deciding something new — e.g. "
                    "see how lofted_spindle builds a loft before reasoning about a similarly-lofted "
                    "shape. Call this ALONE (no propose_parameter_delta in the same turn) when you "
                    "want to see the real source before deciding what to build — it comes back as a "
                    "tool result and you get one more turn to use it."),
                "parameters": read_subsystem_source_tool_schema()}}
            plain_tools.append(read_source_tool)
            strict_tools.append(read_source_tool)
            continuation_handlers[_READ_SUBSYSTEM_SOURCE_FN_NAME] = self._handle_read_subsystem_source_tool_call
        if custom_geometry_enabled():
            custom_geometry_tool = {"type": "function", "function": {
                "name": _CUSTOM_GEOMETRY_FN_NAME,
                "description": (
                    "LAST RESORT: write and register genuinely NEW build123d geometry as a permanent "
                    "catalog subsystem, for a shape the existing catalog (and composing existing "
                    "parts via packages/subsystems/compose.py) genuinely cannot build. Check the "
                    "catalog you were given, and consider composition, BEFORE reaching for this. Call "
                    "this ALONE (no propose_parameter_delta in the same turn) so you see the "
                    "registration outcome before deciding what to do next — it comes back as a tool "
                    "result and you get one more turn to react to it. A rejected candidate is not a "
                    "crash: read rejection_reason and either fix build_code and try again, or fall "
                    "back to an existing catalog part instead. Only on ACCEPTANCE does the new type "
                    "become usable — placing an instance of it is a SEPARATE, later "
                    "propose_parameter_delta add_instance call, not part of this one."),
                "parameters": custom_geometry_tool_schema()}}
            plain_tools.append(custom_geometry_tool)
            strict_tools.append(custom_geometry_tool)
            # This tool needs CALL-SCOPED context (`project_id`, the user's own most recent message)
            # that `_handle_custom_geometry_tool_call` itself can't close over — it's a plain bound
            # method with keyword-only defaults, not a per-call closure (see its own docstring). Built
            # HERE, at the point it's added to `continuation_handlers`, exactly per the "CALL-SCOPED
            # CONTEXT" note above `_handle_research_tool_call` — the shared
            # `continuation_handlers[tc["name"]](tc["arguments"])` call site a few dozen lines down
            # still only ever passes one positional `arguments` string; this closure absorbs the rest.
            # `messages` (not the round-loop's evolving `conversation`) is used deliberately: the
            # user's ORIGINAL most recent message is the request this generation attempt is FOR,
            # computed once, not re-derived from whatever assistant/tool-call scaffolding a
            # continuation round may have appended to `conversation` by the time this fires.
            _custom_geometry_user_excerpt = _last_user_message_text(messages)

            def _custom_geometry_handler(arguments: str) -> "tuple[dict, tuple[str, object] | None]":
                return self._handle_custom_geometry_tool_call(
                    arguments, project_id=project_id, user_request_excerpt=_custom_geometry_user_excerpt)

            continuation_handlers[_CUSTOM_GEOMETRY_FN_NAME] = _custom_geometry_handler
        stable_prompt = build_system_prompt_from_json(ledger_json)
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        conversation = list(messages)
        tool_args: dict[int, str] = {}
        saw_token = False
        finish_reason: str | None = None
        for round_num in range(_MAX_TOOL_ROUNDS):
            round_messages = [{"role": "system",
                                "content": f"{stable_prompt}\n\n## Current ledger\n{ledger_json}"}] \
                              + conversation
            strict_payload = {
                "model": self.model, "max_tokens": self.chat_max_tokens, "stream": True,
                "messages": round_messages, "tools": strict_tools, "tool_choice": "auto",
            }
            plain_payload = {
                "model": self.model, "max_tokens": self.chat_max_tokens, "stream": True,
                "messages": round_messages, "tools": plain_tools, "tool_choice": "auto",
            }
            out: dict = {}
            try:
                for kind, text in self._stream_round_with_strict_fallback(
                        headers, strict_payload, plain_payload, out):
                    saw_token = True
                    yield ("token", text)
            except Exception as e:  # network / bad key / stream error
                yield ("error", str(e))
                yield ("done", None)  # keep the ('error', ...) then ('done', None) contract even here
                return
            round_tool_calls: dict[int, dict] = out["tool_calls"]
            if out["finish_reason"]:
                finish_reason = out["finish_reason"]
            # Generic dispatch (2026-08-06) over `continuation_handlers` — ANY tool call whose name
            # is a key in that dict is a continuation-shaped call, regardless of how many distinct
            # such tools are offered this turn. `tc["name"]` is guaranteed truthy for every entry that
            # matches here: a falsy name falls back to `_FN_NAME` (never a continuation_handlers key,
            # since propose_parameter_delta is deliberately excluded from that dict), so the `or
            # _FN_NAME` fallback below can only ever resolve the PROPOSE classification, never hide a
            # missing continuation-tool name.
            continuation_calls = [tc for tc in round_tool_calls.values()
                                   if (tc["name"] or _FN_NAME) in continuation_handlers]
            propose_calls = {idx: tc["arguments"] for idx, tc in round_tool_calls.items()
                              if (tc["name"] or _FN_NAME) == _FN_NAME}
            tool_result_messages = []
            for tc in continuation_calls:
                # Defense-in-depth (see the "SHARED CONTRACT" note on the dispatch block above): every
                # handler currently here already promises never to raise, but this loop must not
                # silently trust that forever — a future continuation handler (e.g.
                # propose_custom_geometry's sandboxed build) that lets a genuine exception through
                # would otherwise break out of this generator uncaught, bypassing the explicit
                # ('error', ...) + ('done', None) contract stream_chat's own docstring guarantees and
                # falling through to app.py's much coarser route-level backstop instead.
                try:
                    content, event = continuation_handlers[tc["name"]](tc["arguments"])
                except Exception as e:
                    logger.warning("stream_chat: continuation handler %r raised (%s) — this violates "
                                    "the handler's own 'never raise' contract; treating it as a normal "
                                    "stream error instead of letting it propagate uncaught",
                                    tc["name"], e)
                    yield ("error", f"the {tc['name']} tool call failed unexpectedly: {e}")
                    yield ("done", None)
                    return
                if event is not None:
                    yield event
                tool_result_messages.append({
                    "role": "tool", "tool_call_id": tc["id"],
                    "content": json.dumps(content),
                })
            tool_args = propose_calls  # this round's propose calls are authoritative either way
            more_rounds_allowed = round_num < _MAX_TOOL_ROUNDS - 1
            if continuation_calls and not propose_calls and more_rounds_allowed:
                assistant_tool_calls = [
                    {"id": tc["id"], "type": "function",
                     "function": {"name": tc["name"], "arguments": tc["arguments"]}}
                    for tc in continuation_calls
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
            #
            # 2026-08-04 — this branch used to fire with ZERO diagnostic trace: live-reproduced (a
            # user's answer to the copilot's own clarification question — a short, unambiguous reply
            # with no new build info needed — got this exact message), and there was no way to tell
            # afterward whether the completion was genuinely empty, a transport hiccup swallowed
            # somewhere upstream, or something else entirely. Log what's actually known at this point
            # so the NEXT occurrence is diagnosable instead of another guess.
            logger.warning("stream_chat: no response was generated (finish_reason=%r, round_tool_calls=%d, "
                           "saw_token=%r, saw_proposal=%r)", finish_reason, len(round_tool_calls),
                           saw_token, saw_proposal)
            yield ("error", "no response was generated for that message — try rephrasing or asking again")
        yield ("done", None)

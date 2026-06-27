"""The ONE LLM seam — hosted Anthropic vs air-gapped vLLM swap behind an identical interface.

Architecture-blocking decision (PHASE_0 §3a #3): no call site, log sink, or eval harness may
hard-code the Anthropic SDK. Everything goes through `LLMProvider`. A CI lint fails the build on any
`import anthropic` outside this module. This is what makes the ITAR/air-gapped SKU a config swap
rather than a rewrite.

The provider's `propose()` returns a validated `DeltaProposal` — the model is bound to the delta
tool schema with forced tool choice, so prose / free Python cannot come back.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from packages.ledger.deltas import DeltaProposal


class LLMProvider(ABC):
    """Strategic agent (Opus) reasons on the human-timescale turn; the geometric delta-emitter
    (Sonnet) returns a DeltaProposal. The Validator is NOT here — it is a rules/solver router."""

    @abstractmethod
    def propose_delta(self, *, system: str, conversation: list[dict], ledger_json: str) -> DeltaProposal:
        """Emit a DeltaProposal for the current intent. Implementations MUST bind the model to
        `parameter_delta_tool_schema()` with forced tool choice + strict mode."""
        raise NotImplementedError


class NotConfiguredProvider(LLMProvider):
    """Placeholder so the package imports cleanly in Phase 0. Wiring a real provider (hosted Anthropic
    or vLLM) is Phase 1 work — see the cut-list, do not add SDK calls here yet."""

    def propose_delta(self, *, system: str, conversation: list[dict], ledger_json: str) -> DeltaProposal:
        raise NotImplementedError("no LLM provider configured (Phase 1) — see packages/agents/CLAUDE.md")

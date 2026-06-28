"""The ONLY legal LLM emission.

Inversion #1 made concrete: the geometric agent cannot emit free Python or a safety scalar. Its
entire output surface is a `DeltaProposal` — a list of `ParameterDelta`s (or a request for
clarification). Bound to the API with `tool_choice` forced + `strict:true`, prose and code are
impossible at the wire. The schema enforces SHAPE; the rules validator (separate, not an LLM)
enforces INVARIANTS (bounds clamp, HARD_LOCK, coupled invariants).
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from packages.ledger.parameter import LockState

# Nodes the LLM may NEVER target — these are grounded-solver outputs. A delta touching one is rejected.
FORBIDDEN_DELTA_PREFIXES: tuple[str, ...] = ("derived.", "review.")


class ParameterDelta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_node: str = Field(description="dotted ledger path, e.g. 'domains.structure.skin_thickness_mm'")
    requested_value: float
    set_lock: Optional[LockState] = None
    rationale: Optional[str] = None


class DeltaProposal(BaseModel):
    """What the geometric agent returns. Either deltas to apply, or a clarification request when the
    natural-language intent is ambiguous (e.g. '6S', '2 inch', 'make it stronger'). Asking is a
    first-class, rewarded behavior — not a failure."""

    model_config = ConfigDict(extra="forbid")

    deltas: list[ParameterDelta] = Field(default_factory=list)
    request_clarification: Optional[str] = None
    suggestions: list[str] = Field(default_factory=list,
                                   description="quick-reply options to offer with a clarification")


def parameter_delta_tool_schema() -> dict:
    """The strict JSON Schema handed to the Claude tool-use API as the delta-emitter's only tool.
    `extra="forbid"` yields `additionalProperties:false`, so the model cannot smuggle extra fields."""
    return DeltaProposal.model_json_schema()


def is_forbidden_target(node: str) -> bool:
    """True if a delta tries to write a grounded-solver / review node the LLM must never originate."""
    return any(node.startswith(p) for p in FORBIDDEN_DELTA_PREFIXES)

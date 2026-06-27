"""Live smoke test of the real OpenRouter delta-emitter. Skipped unless OPENROUTER_API_KEY is set.

Validates the actual wire (auth, function-calling, parsing) against the live model. Lenient on the
exact delta — the point is that a real call returns a well-formed DeltaProposal without crashing.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.live

_HAS_KEY = bool(os.environ.get("OPENROUTER_API_KEY"))


@pytest.mark.skipif(not _HAS_KEY, reason="OPENROUTER_API_KEY not set")
def test_live_delta_emitter_returns_well_formed_proposal():
    from packages.agents.openrouter_provider import OpenRouterDeltaProvider
    from packages.ledger.deltas import DeltaProposal

    prov = OpenRouterDeltaProvider()
    out = prov.propose_delta(
        system="",
        conversation=[{"role": "user", "content": "set the skin thickness to 3 mm"}],
        ledger_json='{"domains":{"structure":{"skin_thickness_mm":{"value":2.0}}}}',
    )
    assert isinstance(out, DeltaProposal)
    # either it emitted deltas or asked to clarify — both are valid structured outputs
    assert out.deltas or out.request_clarification

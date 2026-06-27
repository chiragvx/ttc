"""A deterministic, offline LLMProvider — the stand-in for the Sonnet delta-emitter.

Lets us build and TEST the agent loop + eval harness with no API key, no cost, no network. It honours
the core inversion: its only output is a `DeltaProposal` (validated deltas) or a clarification request
— never free Python, never a safety scalar. It deliberately asks for clarification on ambiguous intent
("6S", "2 inch", "make it stronger") rather than guessing — the behaviour the evals reward.
"""

from __future__ import annotations

import re

from packages.agents.llm_provider import LLMProvider
from packages.ledger.deltas import DeltaProposal, ParameterDelta

_NUM = re.compile(r"(\d+(?:\.\d+)?)")
SKIN = "domains.structure.skin_thickness_mm"
RIB = "domains.structure.internal_rib_spacing_mm"

_AMBIGUOUS = ("stronger", "beef", "6s", "2 inch", "bigger", "better")


class MockProvider(LLMProvider):
    def propose_delta(self, *, system: str, conversation: list[dict], ledger_json: str) -> DeltaProposal:
        text = (conversation[-1]["content"] if conversation else "").lower()

        if "skin" in text:
            m = _NUM.search(text)
            if m:
                return DeltaProposal(deltas=[ParameterDelta(target_node=SKIN, requested_value=float(m.group(1)),
                                                            rationale="set skin thickness")])
            return DeltaProposal(request_clarification="What skin thickness (mm) would you like?")

        if "rib" in text:
            m = _NUM.search(text)
            if m:
                return DeltaProposal(deltas=[ParameterDelta(target_node=RIB, requested_value=float(m.group(1)))])
            return DeltaProposal(request_clarification="What rib spacing (mm) would you like?")

        if any(a in text for a in _AMBIGUOUS):
            return DeltaProposal(request_clarification="Ambiguous — which parameter, and what target value/units?")

        return DeltaProposal(request_clarification="I couldn't map that to a parameter. Can you be specific?")

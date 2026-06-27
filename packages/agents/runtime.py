"""The co-modeling session — the manual propose -> review -> commit loop.

Honors the human-in-the-loop FSM: the LLM's deltas are AI-PROPOSED (applied only to a TRIAL ledger to
preview the outcome); a separate explicit human `accept` commits them as facts; `signoff` makes the
state export-eligible. Nothing the LLM proposes silently mutates the source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass

from packages.agents.llm_provider import LLMProvider
from packages.ledger.apply import ApplyOutcome, apply_delta
from packages.ledger.deltas import DeltaProposal, ParameterDelta
from packages.ledger.events import EventLog


@dataclass
class ProposeResult:
    proposal: DeltaProposal
    trial_outcomes: list[ApplyOutcome]   # what WOULD happen (preview), not committed

    @property
    def needs_clarification(self) -> bool:
        return self.proposal.request_clarification is not None


class CoModelingSession:
    def __init__(self, provider: LLMProvider, log: EventLog) -> None:
        self.provider = provider
        self.log = log

    def propose(self, intent: str, *, ts: str, actor: str = "user") -> ProposeResult:
        self.log.append_nl_intent(intent, actor=actor, ts=ts)
        proposal = self.provider.propose_delta(
            system="emit parameter deltas only",
            conversation=[{"role": "user", "content": intent}],
            ledger_json=self.log.fold().model_dump_json(),
        )
        led = self.log.fold()
        outcomes = [apply_delta(led, d)[1] for d in proposal.deltas]  # trial only
        return ProposeResult(proposal, outcomes)

    def accept(self, delta: ParameterDelta, *, ts: str, actor: str = "engineer") -> None:
        """Human accepts an AI-proposed delta -> commit as a fact (the review boundary)."""
        self.log.append_mutation(delta, actor=actor, ts=ts)

    def signoff(self, reviewer: str, *, ts: str) -> None:
        self.log.append_signoff(reviewer, ts=ts)

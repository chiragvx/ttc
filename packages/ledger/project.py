"""Project = named branches over the event-sourced ledger, with compare + invariant-aware merge.

Implements the Phase 3 branching/versioning surface on top of `EventLog` (copy-on-write fork) and
`merge_ledgers` (the invariant-aware 3-way merge). Branch comparison scores each branch against a
requirements matrix — answering "which branch is better" by requirements satisfied, not raw params.
"""

from __future__ import annotations

from packages.ledger.branch import MergeResult, merge_ledgers
from packages.ledger.deltas import ParameterDelta
from packages.ledger.events import EventLog
from packages.ledger.requirements import VerificationMatrix
from packages.ledger.schema import MasterParametricLedger


class Project:
    def __init__(self, name: str, genesis_ledger: MasterParametricLedger, *, ts: str, actor: str = "system") -> None:
        self.name = name
        main = EventLog()
        main.append_genesis(genesis_ledger, actor=actor, ts=ts)
        self._branches: dict[str, EventLog] = {"main": main}

    def branches(self) -> list[str]:
        return sorted(self._branches)

    def log(self, branch: str = "main") -> EventLog:
        return self._branches[branch]

    def ledger(self, branch: str = "main") -> MasterParametricLedger:
        return self._branches[branch].fold()

    def fork(self, dst: str, *, src: str = "main") -> EventLog:
        if dst in self._branches:
            raise ValueError(f"branch '{dst}' already exists")
        self._branches[dst] = self._branches[src].clone()
        return self._branches[dst]

    def mutate(self, branch: str, delta: ParameterDelta, *, actor: str, ts: str) -> None:
        self._branches[branch].append_mutation(delta, actor=actor, ts=ts)

    def merge(self, *, base: str, ours: str, theirs: str) -> MergeResult:
        return merge_ledgers(self.ledger(base), self.ledger(ours), self.ledger(theirs))

    def compare(self, matrix: VerificationMatrix, metrics_by_branch: dict[str, dict[str, float | None]]) -> dict[str, int]:
        """Branch -> number of requirements satisfied (the 'which branch is better' answer)."""
        return {b: matrix.score(m) for b, m in metrics_by_branch.items()}

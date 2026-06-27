"""Requirements & verification traceability — the systems-engineering backbone.

Closes the "no requirements model" gap: links each top-level requirement (range, stall, FS, mass) to
the parameters/derivations that satisfy it and a verification method, so the system can answer:
  * is this requirement met? (evaluate)
  * which requirement bounds this parameter? (affected_by — what a weight-shaving change might break)
  * which branch satisfies more requirements? (score)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class VerificationMethod(str, Enum):
    ANALYSIS = "ANALYSIS"
    TEST = "TEST"
    INSPECTION = "INSPECTION"


class ReqStatus(str, Enum):
    SATISFIED = "SATISFIED"
    VIOLATED = "VIOLATED"
    UNKNOWN = "UNKNOWN"  # metric unavailable -> blocks, never assumed satisfied


@dataclass(frozen=True)
class Requirement:
    id: str
    text: str
    metric: str                 # e.g. "factor_of_safety", "mass_g"
    op: str                     # ">=" or "<="
    target: float
    method: VerificationMethod = VerificationMethod.ANALYSIS
    allocated_to: tuple[str, ...] = ()   # ledger paths this requirement constrains

    def check(self, value: float | None) -> ReqStatus:
        if value is None:
            return ReqStatus.UNKNOWN
        ok = value >= self.target if self.op == ">=" else value <= self.target
        return ReqStatus.SATISFIED if ok else ReqStatus.VIOLATED


@dataclass
class RequirementResult:
    requirement: Requirement
    status: ReqStatus
    value: float | None


@dataclass
class VerificationMatrix:
    requirements: list[Requirement] = field(default_factory=list)

    def evaluate(self, metrics: dict[str, float | None]) -> list[RequirementResult]:
        return [RequirementResult(r, r.check(metrics.get(r.metric)), metrics.get(r.metric))
                for r in self.requirements]

    def score(self, metrics: dict[str, float | None]) -> int:
        """Number of SATISFIED requirements — the basis for 'which branch is better'."""
        return sum(1 for res in self.evaluate(metrics) if res.status is ReqStatus.SATISFIED)

    def unmet(self, metrics: dict[str, float | None]) -> list[RequirementResult]:
        return [res for res in self.evaluate(metrics) if res.status is not ReqStatus.SATISFIED]

    def affected_by(self, node: str) -> list[Requirement]:
        """Requirements that allocate to `node` — i.e. which requirements a change here might break."""
        return [r for r in self.requirements if node in r.allocated_to]

"""The Strategic Systems Engineer (macro layer) — mission goal -> a verification requirements set.

Completes the three-role architecture: the strategic agent translates a high-level natural-language
goal ("a bracket that holds 200 N at FS 2, prints under 2 h, stays under 30 g") into a structured
`VerificationMatrix` the rest of the system verifies geometry against. Like the delta-emitter it never
originates a safety scalar — it sets TARGETS (requirements); the solvers later produce the values.

Vendor-agnostic: `StrategicProvider` is the seam; `HeuristicStrategicProvider` is a deterministic
rule-based parser (an OpenRouter strategic provider would emit the same `RequirementSpec` list via
tool-use). It is a real heuristic, not a fake LLM — the product uses no mock providers.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, replace

from packages.ledger.requirements import Requirement, VerificationMatrix, VerificationMethod


@dataclass(frozen=True)
class RequirementSpec:
    text: str
    metric: str
    op: str
    target: float
    method: str = "ANALYSIS"


class StrategicProvider(ABC):
    @abstractmethod
    def plan_requirements(self, goal: str, *, inject_default_fs: bool = True) -> list[RequirementSpec]:
        """Parse a goal into requirement TARGETS. With inject_default_fs, a default FS floor is added
        when none is stated (full-goal planning); without it, only explicitly-stated targets are
        returned (incremental extraction from a chat message)."""


_FS = re.compile(r"(?:fs|factor of safety)\s*(?:of|=|>=)?\s*([0-9]+(?:\.[0-9]+)?)", re.I)
_MASS = re.compile(r"(?:under|<=|below|max)?\s*([0-9]+(?:\.[0-9]+)?)\s*g(?:rams)?\b", re.I)
_HOURS = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*(?:h|hr|hour)", re.I)


class HeuristicStrategicProvider(StrategicProvider):
    """Deterministic, rule-based goal -> requirements (no LLM)."""

    def plan_requirements(self, goal: str, *, inject_default_fs: bool = True) -> list[RequirementSpec]:
        specs: list[RequirementSpec] = []
        if (m := _FS.search(goal)):
            specs.append(RequirementSpec(f"factor of safety >= {m.group(1)}", "factor_of_safety", ">=", float(m.group(1))))
        if (m := _MASS.search(goal)):
            specs.append(RequirementSpec(f"mass <= {m.group(1)} g", "mass_g", "<=", float(m.group(1)), "TEST"))
        if (m := _HOURS.search(goal)):
            secs = float(m.group(1)) * 3600.0
            specs.append(RequirementSpec(f"print time <= {m.group(1)} h", "print_time_s", "<=", secs))
        if inject_default_fs and not any(s.metric == "factor_of_safety" for s in specs):
            specs.append(RequirementSpec("default factor of safety >= 1.5", "factor_of_safety", ">=", 1.5))
        return specs


class StrategicAgent:
    def __init__(self, provider: StrategicProvider | None = None) -> None:
        self.provider = provider or HeuristicStrategicProvider()

    def plan(self, goal: str) -> VerificationMatrix:
        specs = self.provider.plan_requirements(goal)
        reqs = [Requirement(id=f"R{i+1}", text=s.text, metric=s.metric, op=s.op, target=s.target,
                            method=VerificationMethod(s.method)) for i, s in enumerate(specs)]
        return VerificationMatrix(reqs)

    def merge(self, matrix: VerificationMatrix, message: str) -> VerificationMatrix:
        """Fold any TARGETS stated in a chat message into the existing matrix (upsert by metric). A
        message with no recognizable target leaves the matrix untouched — so ordinary chat doesn't wipe
        the goal. This is what lets the chat be the single input: goals accrete as the conversation goes."""
        specs = self.provider.plan_requirements(message, inject_default_fs=False)
        if not specs:
            return matrix
        by_metric = {r.metric: r for r in matrix.requirements}
        for s in specs:
            by_metric[s.metric] = Requirement(id="", text=s.text, metric=s.metric, op=s.op,
                                              target=s.target, method=VerificationMethod(s.method))
        reqs = [replace(r, id=f"R{i+1}") for i, r in enumerate(by_metric.values())]
        return VerificationMatrix(reqs)

    def floor_fs(self, matrix: VerificationMatrix) -> float | None:
        """The strictest FS requirement -> the export-gate floor the goal implies."""
        fs = [r.target for r in matrix.requirements if r.metric == "factor_of_safety" and r.op == ">="]
        return max(fs) if fs else None

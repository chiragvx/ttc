"""The Strategic Systems Engineer (macro layer) — mission goal -> a verification requirements set.

Completes the three-role architecture: the strategic agent translates a high-level natural-language
goal ("a bracket that holds 200 N at FS 2, prints under 2 h, stays under 30 g") into a structured
`VerificationMatrix` the rest of the system verifies geometry against. Like the delta-emitter it never
originates a safety scalar — it sets TARGETS (requirements); the solvers later produce the values.

Vendor-agnostic: `StrategicProvider` is the seam; `MockStrategicProvider` is the deterministic offline
stand-in (an OpenRouter strategic provider would emit the same `RequirementSpec` list via tool-use).
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass

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
    def plan_requirements(self, goal: str) -> list[RequirementSpec]: ...


_FS = re.compile(r"(?:fs|factor of safety)\s*(?:of|=|>=)?\s*([0-9]+(?:\.[0-9]+)?)", re.I)
_MASS = re.compile(r"(?:under|<=|below|max)?\s*([0-9]+(?:\.[0-9]+)?)\s*g(?:rams)?\b", re.I)
_HOURS = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*(?:h|hr|hour)", re.I)


class MockStrategicProvider(StrategicProvider):
    """Deterministic goal -> requirements (offline stand-in for the strategic LLM)."""

    def plan_requirements(self, goal: str) -> list[RequirementSpec]:
        specs: list[RequirementSpec] = []
        if (m := _FS.search(goal)):
            specs.append(RequirementSpec(f"factor of safety >= {m.group(1)}", "factor_of_safety", ">=", float(m.group(1))))
        if (m := _MASS.search(goal)):
            specs.append(RequirementSpec(f"mass <= {m.group(1)} g", "mass_g", "<=", float(m.group(1)), "TEST"))
        if (m := _HOURS.search(goal)):
            secs = float(m.group(1)) * 3600.0
            specs.append(RequirementSpec(f"print time <= {m.group(1)} h", "print_time_s", "<=", secs))
        if not any(s.metric == "factor_of_safety" for s in specs):
            specs.append(RequirementSpec("default factor of safety >= 1.5", "factor_of_safety", ">=", 1.5))
        return specs


class StrategicAgent:
    def __init__(self, provider: StrategicProvider | None = None) -> None:
        self.provider = provider or MockStrategicProvider()

    def plan(self, goal: str) -> VerificationMatrix:
        specs = self.provider.plan_requirements(goal)
        reqs = [Requirement(id=f"R{i+1}", text=s.text, metric=s.metric, op=s.op, target=s.target,
                            method=VerificationMethod(s.method)) for i, s in enumerate(specs)]
        return VerificationMatrix(reqs)

    def floor_fs(self, matrix: VerificationMatrix) -> float | None:
        """The strictest FS requirement -> the export-gate floor the goal implies."""
        fs = [r.target for r in matrix.requirements if r.metric == "factor_of_safety" and r.op == ">="]
        return max(fs) if fs else None

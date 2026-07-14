"""Discipline registry — the analysis-lens axis (structures, manufacturing, thermal, …).

Adding a discipline: create packages/disciplines/<name>.py, build a DisciplineSpec, call register().
The prompt builder, rules validator, export gates, and geometry signature all pull from this registry
— no other file changes. Grounding rule: every discipline number is a closed-form check or a real
solver verdict, or it is `unknown` and blocks export. The LLM never originates a safety scalar.
"""

from __future__ import annotations

from packages.disciplines.base import DisciplineSpec, GateFinding, always_active
from packages.ledger.schema import MasterParametricLedger

DISCIPLINE_REGISTRY: dict[str, DisciplineSpec] = {}


def register(spec: DisciplineSpec) -> DisciplineSpec:
    DISCIPLINE_REGISTRY[spec.name] = spec
    return spec


def get_discipline(name: str) -> DisciplineSpec:
    if name not in DISCIPLINE_REGISTRY:
        raise KeyError(f"Unknown discipline {name!r}. Available: {sorted(DISCIPLINE_REGISTRY)}")
    return DISCIPLINE_REGISTRY[name]


def active_disciplines(ledger: MasterParametricLedger) -> list[DisciplineSpec]:
    return [s for s in DISCIPLINE_REGISTRY.values() if s.is_active(ledger)]


def all_discipline_invariants(ledger: MasterParametricLedger) -> list[str]:
    """Union of active disciplines' L0 apply-time invariants (for apply.py's domain_checks seam)."""
    out: list[str] = []
    for s in active_disciplines(ledger):
        out.extend(s.check_invariants(ledger))
    return out


def all_discipline_findings(ledger: MasterParametricLedger) -> tuple[list[str], list[str]]:
    """Union of active disciplines' export-gate contributions -> (reasons, unknowns).
    Wired into gates.evaluate_export_gates via its `extra_findings` seam."""
    reasons: list[str] = []
    unknowns: list[str] = []
    for s in active_disciplines(ledger):
        finding = s.evaluate_gate(ledger)
        reasons.extend(finding.reasons)
        unknowns.extend(finding.unknowns)
    return reasons, unknowns


def all_geometry_params(ledger: MasterParametricLedger) -> tuple[str, ...]:
    """Union of active disciplines' geometry-affecting params (for the verdict signature)."""
    out: list[str] = []
    for s in active_disciplines(ledger):
        for p in s.geometry_params:
            if p not in out:
                out.append(p)
    return tuple(out)


def active_discipline_fragments(ledger: MasterParametricLedger) -> str:
    """Concatenated knowledge fragments for the disciplines live on this ledger (for the LLM prompt)."""
    return "\n\n".join(s.knowledge_fragment for s in active_disciplines(ledger))


# Side-effect imports: each module calls register() on load. Order = display order.
from packages.disciplines import structures as _structures  # noqa: E402, F401
from packages.disciplines import manufacturing as _manufacturing  # noqa: E402, F401
from packages.disciplines import thermal as _thermal  # noqa: E402, F401
from packages.disciplines import cost as _cost  # noqa: E402, F401

"""DisciplineSpec — the self-describing unit of an analysis lens (structures, thermal, …).

A discipline is the "which physics am I reasoning about?" axis (orthogonal to the subsystem/part axis
in packages/domains/). Each discipline owns the params it cares about, a knowledge fragment for the
LLM, closed-form (L0) invariants, and an export-gate contribution. The SCALAR in any gate comes from a
closed-form check or a real solver verdict — never an LLM token (Inversion #1). A discipline whose
grounded number is missing reports it as an `unknown`, which blocks export.

See build-plan/reference/DOMAIN_TAXONOMY.md for the full disciplines × subsystems model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Union

if TYPE_CHECKING:
    from packages.ledger.schema import MasterParametricLedger


@dataclass(frozen=True)
class GateFinding:
    """One discipline's contribution to the export decision.
    `reasons` block export; `unknowns` are missing grounded scalars (also block — Inversion #1)."""

    reasons: list[str] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)


def always_active(ledger: "MasterParametricLedger") -> bool:
    return True


def _no_invariants(ledger: "MasterParametricLedger") -> list[str]:
    return []


def _no_gate(ledger: "MasterParametricLedger") -> GateFinding:
    return GateFinding()


@dataclass(frozen=True)
class DisciplineSpec:
    name: str
    description: str
    # A plain string (the common case) OR a zero-arg callable returning one — 2026-07-15, so a
    # discipline whose fragment cites live reference data (packages/catalog) can rebuild it at PROMPT
    # time instead of freezing whatever packages.catalog held at IMPORT time (module import happens
    # long before packages/catalog/bootstrap.py::apply_to_live_app() ever runs). See
    # packages/disciplines/__init__.py::active_discipline_fragments, the one place this is resolved.
    knowledge_fragment: Union[str, Callable[[], str]]
    owned_params: tuple[str, ...] = ()
    # subset of owned_params that changes the analyzed geometry (feeds the verdict signature)
    geometry_params: tuple[str, ...] = ()
    # is this discipline live for this ledger? (e.g. thermal only when a thermal domain is present)
    is_active: Callable[["MasterParametricLedger"], bool] = always_active
    # L0 closed-form checks that block a delta at apply time (rare; most rules are gates, not invariants)
    check_invariants: Callable[["MasterParametricLedger"], list[str]] = _no_invariants
    # this discipline's contribution to the export gate (closed-form now; solver-fed later)
    evaluate_gate: Callable[["MasterParametricLedger"], GateFinding] = _no_gate

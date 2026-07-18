"""Couplings — the load-propagation plane (Phase 2, 2026-07-19).

A coupling DERIVES a load on one part from a registered, deterministic RELATION over source
parts/duty, instead of the load being a stated scalar. This is the "casing pressure change cracked the
crankshaft" behaviour made computable (ENGINEERING_GRAPH_ARCHITECTURE.md §2). Pure arithmetic — NO
OCCT, NO LLM, NO solver, NO I/O — so it runs on the closed-form tier and the LLM can never author the
physics (it only WIRES which registered relation connects which parts; Inversion #1).

Public surface:
- `RELATION_REGISTRY`, `get_relation`, `Relation` — the versioned catalog of physical relationships.
- `resolve_couplings(ledger)` -> per-target derived load or "unknown" (relation not in the catalog, or
  a missing input) — never a fabricated number.
"""

from packages.couplings.relations import RELATION_REGISTRY, Relation, get_relation
from packages.couplings.resolve import (
    CouplingResult,
    coupling_gate_findings,
    derived_load_n,
    resolve_couplings,
)

__all__ = [
    "RELATION_REGISTRY", "Relation", "get_relation",
    "CouplingResult", "resolve_couplings", "coupling_gate_findings", "derived_load_n",
]

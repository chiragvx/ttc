# Phase 3 — Scale / Aerospace (Backbone)

**Status:** 🟡 Core *architecture* implemented & tested; scale-infra + aerospace physics remain
**Goal:** multi-tenant, audit-ready, controlled-data-capable; aerospace physics behind the wedge.

## Done (in code, tested)

| Capability | Module | Tests |
|---|---|---|
| **Branching + invariant-aware 3-way merge** (scalars merge; divergent/invariant-breaking → CONFLICT; no silent last-writer-wins) | `packages/ledger/branch.py` | `tests/backend/test_branch.py` |
| **Event-sourcing with content-addressed derivations + toolchain fingerprint** (replay never recomputes — the AS9100/traceability property) | `packages/ledger/events.py`, `fingerprint.py` | `tests/ledger/test_events.py` |
| `LLMProvider` seam ready for the **air-gapped/vLLM** swap (CI lint forbids SDK imports elsewhere) | `packages/agents/llm_provider.py` | `scripts/check_llm_provider_imports.py` |

## Remains (gated — infra / corpus / hires / explicitly-cut)

- **Multi-tenancy** (Postgres RLS), **durable orchestration** (Temporal DAGs), **autoscale** (KEDA) —
  running infrastructure, not in scope for a single-box backbone.
- **Air-gapped vLLM ITAR SKU** — provider seam ready; needs the deployment + export gating + counsel.
- **NSGA-II / qEHVI optimizer + GP/POD surrogates** — needs a labeled solver corpus that only exists
  after the product has run thousands of solves (do NOT pull forward — see cut-list).
- **Aerospace physics** (flutter/DLM, AVL/XFOIL aero, propulsion/range, kinematics/swept-volume,
  bonded-joint cohesive FEA) — **deliberately cut** from the wedge (root `CLAUDE.md`).
- **arm64 / cross-OCCT-version determinism** — needs that hardware / those toolchains.
- Real **Yjs/Automerge CRDT** for live multi-user co-edit — the deterministic 3-way merge here covers
  the *safety semantics* (invariant-aware, conflict-surfacing); live co-editing is the richer version.

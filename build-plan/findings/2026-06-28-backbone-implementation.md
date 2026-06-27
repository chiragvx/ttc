# Finding — Phases 1–3 backbone implemented in one push

**Date:** 2026-06-28 · **Type:** implementation milestone

## What was built

In response to "complete all other phases in a single shot", the **load-bearing architecture of
Phases 1–3** was implemented in code and tested. This is the buildable backbone — not a shippable
product (see "Honest boundary").

| Area | Modules | What it proves |
|---|---|---|
| Phase 1 — rules validator | `ledger/apply.py` | the LLM proposes; deterministic code decides (clamp/lock/forbidden/conflict) |
| Phase 1 — event store + replay | `ledger/events.py`, `fingerprint.py` | FACTS vs DERIVATIONS, hash chain, **pure-fold replay never re-invokes LLM/solver** (risk #3) |
| Phase 2 — requirements | `ledger/requirements.py` | goal→param→verify traceability; `affected_by`, branch `score` |
| Phase 2 — BOM/material/datum | `ledger/bom.py`, `datum.py` | mass/CG computable; material has real props; shared frame + %MAC |
| Phase 2 — agent loop | `agents/{llm_provider,mock_provider,runtime,eval}.py` | propose→review→commit FSM; evals grade the delta; clarify-not-guess |
| Phase 2 — transport | `transport/{protocol,app}.py` | two-plane WS + Tier-0 telemetry + the **NACK** the PRD lacked |
| Phase 2 — estimator | `truth_plane/solvers/slicer_estimate.py` | analytic print/material + overhang (labeled estimate) |
| Phase 3 — branching/merge | `ledger/branch.py` | **invariant-aware** 3-way merge; conflicts surface; no silent LWW |
| Phase 1 — tagged generator | `truth_plane/regen/templated.py` | Spike 1 fallback #1: generator-deterministic tags survive regen |

**Tests:** 54 passing in the Linux container (50 + 4 `needs_solver` on Windows). ruff clean; the
copyleft + LLMProvider-seam gates pass. Everything imports without the kernel (pure backbone) and the
kernel/solver tests run in the image.

## Honest boundary — what "backbone" does NOT include

Genuinely gated on infrastructure, a frontend, API keys, or specialists — **not** built:

- **Frontend** — the React/r3f viewport (the whole UI).
- **Sandbox** — Firecracker/gVisor microVM execution (Linux KVM + security review).
- **Persistence** — Postgres-backed event store, RLS multi-tenancy (in-memory `EventLog` today).
- **Real LLM** — Opus/Sonnet behind the seam (mock provider stands in; needs a key + tool-use wiring).
- **Real slicer** — network-isolated PrusaSlicer sidecar (AGPL boundary; analytic estimator today).
- **Scale-infra** — Temporal, KEDA, the air-gapped vLLM SKU.
- **Optimizer** — NSGA-II + surrogates (needs a corpus that doesn't exist yet — do not pull forward).
- **Aerospace physics** — flutter/aero/propulsion/kinematics (deliberately cut from the wedge).
- **Specialist spikes** — Spike 1 face-level identity (OCCT eng), 20-geo FEA robustness (FEA eng),
  arm64/cross-version determinism, the legal §3a decisions (counsel).

## Why this is still meaningful

The architecture's three inversions are now *executable and enforced by tests*, not just asserted:
the LLM cannot write a safety scalar (rules validator + forbidden-target + tool schema), replay is a
pure fold (tripwire-style test), and a missing safety number blocks export. The remaining work is
substantial but is *integration, infrastructure, and specialist judgment* on top of a proven spine —
not unresolved architectural risk.

## Reproduce

```
python -m pytest -q                                   # 50 passed, 4 skipped (host)
docker run --rm gtc-dev python -m pytest -q           # 54 passed (kernel+solver)
```

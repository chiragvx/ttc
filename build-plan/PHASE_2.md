# Phase 2 — MVP (Backbone)

**Status:** 🟢 Backbone implemented & tested (frontend + real LLM/slicer + physical correlation remain)
**Goal:** a grounded, single-tenant product with human-in-the-loop sign-off.

## Done (in code, tested)

| Capability | Module | Tests |
|---|---|---|
| **Requirements / verification traceability** (goal→param→verify; `affected_by`, `score`) | `packages/ledger/requirements.py` | `tests/ledger/test_requirements_bom.py` |
| **Positioned BOM + material DB** → computable mass/CG (closes "mass uncomputable" + "material is a bare string") | `packages/ledger/bom.py` | same |
| **Datum frame** (shared body frame, placement, %MAC) | `packages/ledger/datum.py` | same |
| **propose → review → commit** session (AI-proposed, human accept commits, sign-off → export-eligible) | `packages/agents/runtime.py` | `tests/backend/test_agents.py` |
| Agent layer: `LLMProvider` seam + **deterministic mock provider** + **eval harness** (grades the structured delta; clarify-not-guess) | `packages/agents/{llm_provider,mock_provider,eval}.py` | `tests/backend/test_agents.py` |
| **Real Anthropic delta-emitter** (forced tool-use, strict schema, refusal-handling; SDK imported lazily, tested via injected fake client) | `packages/agents/anthropic_provider.py` | `tests/backend/test_anthropic_provider.py` |
| **Two-plane WebSocket** + Tier-0 telemetry + the **NACK** the PRD lacked | `packages/transport/{protocol,app}.py` | `tests/backend/test_app.py` |
| Print/material **estimator** + supportless-overhang check | `packages/truth_plane/solvers/slicer_estimate.py` | `tests/backend/test_slicer_estimate.py` |

## Remains (gated)

- **3D viewport** (React + r3f, read-only, morph preview, anchored HUD) — frontend build; not started.
- **Real LLM provider** — the Sonnet delta-emitter is built & wired (`anthropic_provider.py`, forced
  tool-use); it just needs an **API key** to run live (and the Opus strategic agent + prompt-caching
  layer on top). The tool-use parsing is already tested via an injected fake client.
- **Real PrusaSlicer sidecar** (network-isolated, AGPL boundary) — replaces the analytic estimator for
  the authoritative number. → architecture-blocking decision §3a (counsel).
- **FEA convergence/cross-validation suite + 20-geometry meshing-robustness sweep** — → FEA engineer.
- **Physical "prints-and-fits + load-test" correlation** — → design partner with a load frame.

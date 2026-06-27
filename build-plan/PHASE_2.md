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
| **Strategic agent (macro layer)** — mission goal → verification requirements matrix | `packages/agents/strategic.py` | `tests/backend/test_strategic.py` |
| **3D viewport** — Vite + React + react-three-fiber, three-zone layout, bounded sliders + HARD_LOCK, telemetry HUD + NACK surface; **builds clean** (tsc + vite) | `packages/frontend/` | `npm run build` |
| Runtime **CLI** + per-design **cost/token accounting** (USAGE events) | `packages/cli.py`, `packages/ledger/cost.py` | `tests/backend/test_cli.py`, `tests/ledger/test_cost.py` |

## Remains (gated)

- **3D viewport** — built & compiles (`packages/frontend/`). Remaining: wire the real glTF mesh from
  kernel regen (Tier 1), morph-target preview, and anchored HUD; live end-to-end against a running
  backend (`uvicorn ... --factory` + `npm run dev`).
- **Real LLM provider** — the OpenRouter (DeepSeek) delta-emitter is built & wired
  (`openrouter_provider.py`, forced function-calling); it just needs an **API key** to run live
  (`OPENROUTER_API_KEY`; CI has a key-gated live-smoke job). The strategic macro agent is built (mock);
  its OpenRouter wiring is the same pattern as the delta provider.
- **Real PrusaSlicer sidecar** (network-isolated, AGPL boundary) — replaces the analytic estimator for
  the authoritative number. → architecture-blocking decision §3a (counsel).
- **FEA convergence/cross-validation suite + 20-geometry meshing-robustness sweep** — → FEA engineer.
- **Physical "prints-and-fits + load-test" correlation** — → design partner with a load frame.

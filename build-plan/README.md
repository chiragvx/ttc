# Grounded Text-to-CAD — Build Program Tracker

Master index for turning the `prd-27-8.14` vision into a real product, engineered with Claude
(dev-time) and powered by Claude (runtime).

**Last updated:** 2026-06-28
**Current phase:** Phases 0–4 implemented & green (**92 backend tests pass on Windows**, more in the
container) and the **full wedge stack runs end-to-end on `docker compose up`**. Spike 4 fully PASSES
(deflection-validated FS + 19/19 auto-mesh). Built across the phases: ledger + rules validator + event
store/replay (in-mem + SQL + **Postgres**), hero-bracket end-to-end, sandbox kill-primitives,
**strategic macro agent**, **OpenRouter/DeepSeek delta-emitter** + runtime **CLI**, **derived-resolution
+ Dramatiq FS jobs**, **live `/optimize` 3-variant sweep**, **project/branch service**, **neutral
STEP/STL export**, **cost accounting**, and a **React + react-three-fiber chat frontend** (builds clean).
The live loop — chat/slider → real CalculiX FS / optimize → export gate flips ELIGIBLE → STEP — is
verified on compose. Gated/remaining: live keys (CI secret), microVM isolation, PG **RLS**/multi-tenant
auth, real slicer cost, WS status push (currently polling), scale-infra, and the specialist spikes
(OCAF identity, FEA methodology, legal).

> ⚠️ Host note: the dev machine's **C: drive is full** — point Python/npm temp at D:
> (`TEMP=D:/pytmp`) or tests that write temp files will hit `OSError: No space left on device`.

---

## The strategic call (read this first)

> **Do not build the aerospace UAV product first.** Build a **conversational generator for
> functional printable/machinable parts** — brackets, mounts, enclosures, fixtures, jigs — with
> real DFM, a real slicer-backed cost/time number, and a real Gmsh+CalculiX factor-of-safety
> under *one* declared load.

This wedge exercises every load-bearing thesis while shedding everything un-shippable (flutter,
CFD aero, propulsion/range, kinematics, bonded-joint FEA, ITAR, AS9100). **Aerospace is the
Series A/B narrative, matured behind the wedge — never the thing we build first.**

## The three inversions (non-negotiable — pin these in every `CLAUDE.md`)

1. **The LLM never originates a safety scalar and never emits free Python.** It emits
   Pydantic-validated parameter deltas; a deterministic Jinja2 + build123d templater renders the
   script; real solvers (Gmsh+CalculiX, etc.) produce every FS/stall/flutter/range number. Missing
   inputs → `"unknown"` (blocks export), never a fabricated green light.
2. **The single clock is a fiction.** Three honest tiers: 30 Hz analytic HUD / kernel regen on
   slider-release / minutes-scale solver+optimizer DAG.
3. **Persistent topological identity** (generator-baked tags + OCAF/TNaming) is the keystone bet.

## Architecture spine

Grounded **two-plane Python monolith**: an Interactive Plane (closed-form, in-process, <1 ms/number)
and a Truth Plane (OCCT regen, FEA, slicing, optimization — durable async jobs, content-addressed,
never blocks a frame, never re-invoked on replay). Full detail: [`reference/TECH_PLAN.md`](reference/TECH_PLAN.md).

---

## Phase ladder

| Phase | Window | Goal | Status |
|-------|--------|------|--------|
| **0 — De-Risk Spikes** | 0–30 d | Prove/kill the 5 keystone bets | 🟢 Harness green; **determinism** + **Spike 4 (solver)** validated; Spike 1 (identity) partial; legal §3a + arm64 gated → [`PHASE_0.md`](PHASE_0.md) |
| **1 — Foundation** | 30–90 d | Hardened deterministic substrate | 🟢 **Backbone done** (ledger, event store + replay, rules validator, review FSM, determinism, 1 solver) → [`PHASE_1.md`](PHASE_1.md) |
| **2 — MVP** | 3–6 mo | Grounded product w/ human-in-loop | 🟢 **Backbone done** (requirements matrix, BOM/datums, agent loop + evals, WS protocol + NACK, estimator) → [`PHASE_2.md`](PHASE_2.md) |
| **3 — Scale / Aerospace** | 6–12 mo | Multi-tenant, audit-ready | 🟡 **Core arch done** (branching + invariant-aware merge, content-addressed event-sourcing); infra/optimizer/aero gated → [`PHASE_3.md`](PHASE_3.md) |
| **4 — Truth-Plane Activation** | — | The grounded analysis loop, live | 🟢 **Built & verified LIVE on compose**: derived-resolution, Dramatiq FS jobs, Postgres, `/analyze`→export-flip, **`/optimize` 3-variant sweep via the worker**. End-to-end on `docker compose up`: optimize → real CalculiX → export ELIGIBLE → STEP downloads → [`PHASE_4_truth_plane.md`](PHASE_4_truth_plane.md) |

> "Backbone done" = the load-bearing architecture is implemented in code and green under test. It is
> **not** a shippable product: no frontend, no microVM sandbox, no DB, no real LLM/slicer, no
> scale-infra, and the specialist-gated spikes (identity, FEA robustness, legal) remain. See each
> phase doc's "Remains" section.

> ⚠️ **Timeline realism (from the critique):** Claude accelerates the typed-glue ~50%, but the
> critical path is the OCAF identity bet + FEA correctness — the two things Claude does *not*
> accelerate. Treat **~9–12 months to a defensible product** as the real number; 12–16 weeks gets
> the *foundation slice*, not the MVP.

---

## Repository / docs layout

```
build-plan/
  README.md                  ← this file (program tracker)
  PHASE_0.md                 ← active phase tracker + progress + docs
  spikes/                    ← the 5 kill-criteria docs (the actual Phase 0 artifacts)
    SPIKE_1_topological_identity.md
    SPIKE_2_3_codegen_sandbox.md
    SPIKE_4_solver_fs_roundtrip.md
    SPIKE_5_two_plane_latency.md
  reference/
    TECH_PLAN.md             ← recommended final tech plan (architecture, stack, tiers, event-sourcing)
    PLAYBOOK.md              ← full build playbook (phases, Claude operating model, harness, team)
    gap-analysis-raw.json    ← 8 existential risks, ranked gaps, missing subsystems, judged plans
    playbook-critique.json   ← skeptic reality-check (12 overlooked + 11 overoptimistic items)
```

(Future: `PHASE_1.md`, `PHASE_2.md`, `PHASE_3.md`, plus `decisions/` for the architecture-blocking
decision log once we start resolving them.)

## How to use this tracker

- Each phase has its own `PHASE_N.md` with a live checklist, a progress log, and the exit gate.
- Update the **Status** column above and the phase file's progress log as work lands.
- The reference docs are the durable source of truth; the gap analysis and critique are the
  "why" behind every decision here.

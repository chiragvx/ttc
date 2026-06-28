# Phase 4 — Truth-Plane Activation (the grounded analysis loop, live)

**Status:** 🟢 **DONE & verified live.** Loop green on Windows, real-CalculiX e2e green in the
container, AND the **full wedge stack runs end-to-end via `docker compose up`**: a slider change →
`/analyze` **queued to the Dramatiq worker** → real CalculiX (~8 s) → verdict → the export gate
**flips ELIGIBLE** → Sign off & **Export STEP**; a geometry change makes it **stale**; verdicts +
events **persist in Postgres across a backend restart**. (Docker had wedged on a full C: — fixed by
freeing C: + a hard Docker Desktop restart.)
**Goal:** *chat/slider → change a parameter → real CalculiX FS (durable async job) → the export gate
flips ELIGIBLE in the browser.* Activates the third architecture tier on the documented wedge stack.

## The keystone design — derived resolution

`derived.*` is a **derivation of the current geometry**, not a replayed fact. So a verdict is recorded
keyed by a **geometry signature** (hash of the geometry-affecting params) + toolchain fingerprint, and
the current `derived` is **resolved at read time** from the latest matching verdict — **no match
(params changed) → "unknown" → export blocked.** Replay stays a pure fold over facts; derivations are
resolved, never folded. (`packages/ledger/derived_resolver.py`.)

## Done (in code)

| Piece | Module | Tests |
|---|---|---|
| **Derived resolver** (signature, latest-verdict, resolve, auto-invalidate) | `ledger/derived_resolver.py` | `tests/ledger/test_derived_resolver.py` ✅ |
| **Grounded analysis** (render → CalculiX FS → validity → Verdict; runs in a child process so gmsh gets a main thread) | `truth_plane/analysis.py` | `tests/solvers/test_analysis_flow.py` ✅ (real CalculiX) |
| **Dramatiq actor** (idempotent FS job; StubBroker in tests, Redis in worker) | `truth_plane/jobs.py`, `worker.py` | `tests/backend/test_jobs.py` ✅ |
| **Verdict store** (in-memory + Postgres) | `truth_plane/verdict_store.py`, `ledger/event_store_pg.py` | (pg via compose) |
| **API:** `/analyze` (inline or queued, cached), `/analyze/status`, `/signoff`, `/export/step`; `/export/check` resolver-based | `transport/app.py` | `tests/backend/test_analysis_api.py` ✅ |
| **Postgres persistence** (event store + projects survive restarts) | `ledger/event_store_pg.py` | (compose) |
| **Compose stack** (backend+SPA / worker / redis / postgres) | `docker-compose.yml`, `docker/Dockerfile.app` | (compose) |
| **Frontend:** Analyze rail, FS + solver-time, export chip flip, **stale on change**, **Sign off & Export STEP** | `frontend/src/{AnalysisBar,App,api}` | `npm run build` ✅ |

**Suite:** 91 passed / 15 skipped on Windows; ruff + gates clean; frontend builds. The whole loop
(blocked → analyze → sign-off → **ELIGIBLE** → change → **stale** → re-analyze → eligible, idempotent
cache, real STEP export) is verified in `test_analysis_api.py` with the solver faked (build123d export
is real); the real CalculiX FS is already validated in `test_fs_cantilever` + the hero pipeline.

## Live run

```
docker compose up --build      # -> http://localhost:8000  (backend serves the SPA + solvers)
```
(Docker had wedged on a 100%-full C: — Docker Desktop's data lives on C:. Freeing C: + a hard restart
of Docker Desktop recovered it; the real-CalculiX container e2e is green.) The container test alone:
`docker run --rm -v $PWD:/app gtc-dev pytest tests/solvers/test_analysis_flow.py`.

## Optimization — the 3-variant sweep, wired live

The sanctioned in-scope optimizer (CLAUDE.md cut-list: *use a 3-variant sweep*, not NSGA-II) is now an
**Optimize** action in the running app: find the **lightest** skin that clears the FS floor, then apply it.

| Piece | Module |
|---|---|
| **Sweep + pick** (`_run_optimize`: render each candidate → real CalculiX FS → mass `ρ·A·skin`; pick the thinnest feasible) | `truth_plane/analysis.py` |
| **Subprocess wrapper** (`optimize_in_subprocess`, spawn child — gmsh needs a main thread) | `truth_plane/analysis.py` |
| **Dramatiq actor** `run_optimization` (stores best `Verdict` + variants summary) | `truth_plane/jobs.py`, `worker.py` |
| **API** `POST /optimize` (queued→worker when `REDIS_URL`, else inline/monkeypatchable), `GET /optimize/status` | `transport/app.py` |
| **Optimize-results table** (upsert by project, survives restart) | `ledger/event_store_pg.py`, `verdict_store.py` |
| **Frontend** Optimize button → poll `/optimize/status` → apply best skin via the WS rules path → variants table | `frontend/src/{AnalysisBar,OptimizeResult,App,api}` |

Same uvicorn-can't-spawn constraint as `/analyze`: the sweep runs in the **worker** (where spawn is
clean), the backend only enqueues and the browser polls. `test_analysis_api.py::test_optimize_picks_lightest_feasible_applies_and_flips` covers the inline path (faked solver) — 4 passed.

**Live (compose) verified end-to-end:** `POST /optimize` → `queued` → worker runs the real CalculiX
sweep over skin ∈ {2,3,4,5}mm → FS `0.57 / 1.25 / 2.22 / 3.39` → **best_skin = 4.0** (lightest design
clearing FS ≥ 1.5; 3mm @ 1.25 fails) → frontend applies 4.0 via WS (`2.0→4.0 APPLIED`) → the stored
verdict resolves → export flips **EXPORT_ELIGIBLE** → a real 30 KB ISO-10303-21 **STEP** downloads.

## Goal-grounded conversational design (the AI layer, wired live)

The chat was a stateless delta-puppet — it nudged sliders but had no concept of the user's **goal**.
The strategic requirements layer (`agents/strategic.py`, `ledger/requirements.py`) existed but was
orphaned. Now the session carries the goal as a `VerificationMatrix` and judges the design against it.

| Piece | Module |
|---|---|
| **Goal → targets** (`StrategicAgent.plan`: NL goal → `Requirement`s; never originates a safety value, only TARGETS) | `agents/strategic.py` |
| **Grounded metric snapshot** (`SessionState.metrics`: FS from the **resolved real-solver verdict**, mass/time from deterministic geometry) | `transport/app.py` |
| **API** `POST /requirements` (set goal), `GET /requirements` (compliance readout: per-req SATISFIED/VIOLATED/**UNKNOWN** + `implied_fs_floor`) | `transport/app.py` |
| **Single input** — the goal is stated **in the chat** (no separate box); each user message folds any stated TARGETS into the goal via `StrategicAgent.merge` (upsert by metric; a no-target message is a no-op, so ordinary chat never wipes the goal). The compliance panel is **read-only**. | `agents/strategic.py`, `frontend/src/{chat/Chat,RequirementsCard,App}` |

**The keystone — inversion #1 made conversational:** `factor_of_safety` in the readout comes from the
real verdict, so it is **UNKNOWN until a solver has run for the current geometry** — never assumed
green. Mass / print-time are deterministic geometry and are known immediately. Tests:
`test_requirements_api.py` (goal parse → targets + implied FS floor; FS UNKNOWN→SATISFIED after analyze;
a too-strict goal reported VIOLATED, not hidden) — 4 passed.

**Live (compose) verified:** goal *"holds 200 N at FS 2, under 200 g"* → `implied_fs_floor 2.0`; FS
judged **SATISFIED at 2.22** against the real verdict for the matching geometry; change skin 4→3.5
(no verdict) → FS flips to **UNKNOWN** while mass stays known (160 g). The conversation now knows the
goal and refuses to claim safety it can't prove.

**The goal is ENFORCED, not just reported** (`SessionState.effective_fs_floor` = max(default, goal)):
- The **export gate** raises its FS floor to the goal at read time — an already-eligible design (FS
  2.4 vs default 1.5) goes **BLOCKED** the moment a stricter "FS 3" goal is stated.
- **Optimize is goal-aware** — the sweep targets the effective floor, and the card surfaces a *"Find
  the lightest design meeting FS ≥ N"* action when FS is unmet. Live: with an "FS 3" goal, Optimize
  rejects skin 2/3/4 (FS 0.56/1.24/2.17) and picks **skin 5 (FS 3.36)** — a stronger design than the
  default-floor sweep's skin 4. The LLM sets the target; the deterministic gate + real solver enforce it.

## Domain — a tunable bolt-hole feature (the part gets designable)

The part was a plate with **hardcoded** bolt-holes (`n_holes=4, hole_dia=6mm`) — the agent could only
move wall/rib. Bolt-hole **diameter** is now a tunable ledger param (`manufacturing.hole_diameter_mm`,
bounds 3–10mm), so the AI can design a real feature.

| Piece | Module |
|---|---|
| **Schema param** `hole_diameter_mm` (the hole COUNT stays fixed — it is topology-changing, the OCAF identity wall) | `ledger/schema.py` |
| **In the geometry signature** — resizing a hole invalidates the FS verdict (it changes the stress field) | `ledger/derived_resolver.py` (`GEOMETRY_PARAMS`) |
| **Threaded through** render (`analyze_geometry`), the optimize sweep (held fixed), `/mesh`, `current_params` | `truth_plane/analysis.py`, `transport/app.py` |
| **Frontend** bolt-hole slider + the viewport re-renders the real geometry on resize | `frontend/src/{FloatingControls,Viewport,App}` |

Tests: `test_derived_resolver.py::test_resizing_a_bolt_hole_invalidates_verdict` (Windows). **Live
(compose) verified:** the hole size flows to CalculiX — FS `0.2826` (6mm) vs `0.2802` (9mm) at the
same skin/load, a real signed change (bigger hole → more stress). NB: a schema change needs a demo-DB
reset (`TRUNCATE events,verdicts,optimize_results,artifacts`) — the old genesis lacks the new required
field; in production this is a migration.

## Out of scope (deferred, as planned)

Firecracker/gVisor sandbox (analysis runs trusted templated code); real PrusaSlicer sidecar (analytic
estimator kept); multi-tenant auth/RLS; optimizer beyond the 3-variant sweep (NSGA-II Pareto). Redis
pub/sub → WS `SOLVER_RESULT` push is wired as a *polling* `/analyze/status` + `/optimize/status` for
now (the documented fallback).

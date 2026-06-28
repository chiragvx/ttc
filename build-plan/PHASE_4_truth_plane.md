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

## Out of scope (deferred, as planned)

Firecracker/gVisor sandbox (analysis runs trusted templated code); real PrusaSlicer sidecar (analytic
estimator kept); multi-tenant auth/RLS; optimizer beyond the 3-variant sweep (NSGA-II Pareto). Redis
pub/sub → WS `SOLVER_RESULT` push is wired as a *polling* `/analyze/status` + `/optimize/status` for
now (the documented fallback).

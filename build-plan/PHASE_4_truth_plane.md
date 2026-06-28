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

## Out of scope (deferred, as planned)

Firecracker/gVisor sandbox (analysis runs trusted templated code); real PrusaSlicer sidecar (analytic
estimator kept); multi-tenant auth/RLS; optimizer beyond the 3-variant sweep. Redis pub/sub → WS
`SOLVER_RESULT` push is wired as a *polling* `/analyze/status` for now (the documented fallback).

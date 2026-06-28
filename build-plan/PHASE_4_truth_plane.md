# Phase 4 — Truth-Plane Activation (the grounded analysis loop, live)

**Status:** 🟢 Built & verified (loop logic green on Windows); the full-stack compose run is blocked by
a host issue (Docker unresponsive — C: full), not by the code.
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
| **Grounded analysis** (render → CalculiX FS → validity → Verdict) | `truth_plane/analysis.py` | container e2e (blocked, see below) |
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

## Blocked — host issue (not the code)

`docker compose up` and the container e2e (`tests/solvers/test_analysis_flow.py`, real CalculiX) are
**blocked because Docker is unresponsive** — even a trivial `docker run` hangs. Root cause: **C: is
100% full**, and Docker Desktop's data lives on C:. **Free C:**, then:
```
docker compose up --build      # -> http://localhost:8000
```
The container test runs with `docker run -v $PWD:/app gtc-dev pytest tests/solvers/test_analysis_flow.py`.

## Out of scope (deferred, as planned)

Firecracker/gVisor sandbox (analysis runs trusted templated code); real PrusaSlicer sidecar (analytic
estimator kept); multi-tenant auth/RLS; optimizer beyond the 3-variant sweep. Redis pub/sub → WS
`SOLVER_RESULT` push is wired as a *polling* `/analyze/status` for now (the documented fallback).

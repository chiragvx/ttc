# Grounded Text-to-CAD

An AI-guided, conversational CAD platform that turns natural-language design intent into
**manufacturable** 3D hardware — built so the LLM proposes, and grounded solvers decide.

- **What we're building & why this way:** [`build-plan/README.md`](build-plan/README.md) (program tracker)
- **Current phase:** Phase 4 — Truth-Plane activation, live end-to-end on `docker compose up`
  → [`build-plan/PHASE_4_truth_plane.md`](build-plan/PHASE_4_truth_plane.md)
- **Architecture & guardrails:** [`CLAUDE.md`](CLAUDE.md) · full plan in [`build-plan/reference/`](build-plan/reference/)

## The thesis in three lines

1. The LLM **never** originates a safety number and **never** emits free Python — it emits validated
   parameter deltas; a deterministic templater renders build123d; real solvers produce every FS. A
   missing input is `"unknown"` and **blocks export**.
2. The "single clock" is a fiction — three tiers: 30 Hz analytic HUD / kernel regen on release /
   minutes-scale solver DAG.
3. Persistent topological identity is the keystone bet.

## Dev quickstart

```bash
python -m pip install -e ".[dev]"   # pure-Python backbone deps
python -m pytest -q                  # backbone tests (kernel/solver tests skip without the image)
docker run --rm gtc-dev python -m pytest -q   # full suite (+ determinism, FS, sandbox, robustness)

# the runtime CLI (set OPENROUTER_API_KEY for the DeepSeek emitter; without a key it says "no LLM")
python -m packages.cli propose "make the skin 3 mm"
python -m packages.cli status
```

The runtime LLM is **OpenRouter** (default model `deepseek/deepseek-chat`) — copy `.env.example` to
`.env` and set `OPENROUTER_API_KEY`. **Without a key there is no LLM** (the app says so) — there is no
mock fallback.

Run the full app (backend + 3D frontend):

```bash
pip install -e ".[serve]" && uvicorn packages.transport.app:create_app --factory   # backend :8000
cd packages/frontend && npm install && npm run dev                                  # viewport :5173
```

Or the whole wedge stack (backend + worker + Postgres + Redis + built frontend) in one command:

```bash
docker compose up --build
```

Target runtime is Python 3.12; the local floor is 3.10. The kernel/solver/sandbox stack
(build123d, OCCT, Gmsh, CalculiX, Firecracker/gVisor) is **Linux-only** and lives behind the Truth
Plane — see [`build-plan/PHASE_0.md`](build-plan/PHASE_0.md) §3c for the Linux dev container.

## Layout

```
CLAUDE.md            guardrails loaded into every Claude Code session (the 3 inversions + cut-list)
packages/
  ledger/            source of truth: schema, instance-tree, deltas, rules-validator (apply), event
                     store + replay, gates, requirements matrix, BOM/material DB, branching/merge
  interactive_plane/ Tier-0 closed-form proxies (no OCCT/LLM/solver)
  subsystems/        the part catalog (32 registered types) — ParamSpec/Subsystem registry, compose
                     helpers, assembly composition, generic cut features, pickable-feature layer
  disciplines/       closed-form structures/manufacturing/thermal/cost knowledge fed to the LLM prompt
  catalog/           local, Supabase-ready reference-data store (materials, DFM/cost lookups) —
                     seed-file default, Postgres tier for compose/hosted Supabase later
  truth_plane/analysis.py  grounded FS pipeline generalized to any fea_eligible subsystem
  truth_plane/regen/    determinism probe + tagged templated generator (Spike 1 fallback)
  truth_plane/solvers/  validated CalculiX FS pipeline + print estimator (Linux)
  agents/            LLMProvider seam + OpenRouter provider + prompt_builder + strategic agent + eval
  transport/         FastAPI app (REST + two-plane WebSocket protocol with NACK) — multi-file sessions,
                     instance/feature-op CRUD, export-gate enforcement at the export endpoint itself
  frontend/          React + react-three-fiber chat/viewport/outliner UI, builds and runs against the
                     backend over REST + WS
tests/
  acceptance/        pure-Python safety-contract tests + e2e stories (assembly composition, cut features)
  determinism/       cross-platform B-rep golden gate + mesh probe
  ledger/ backend/   the ledger + REST/WS backbone (apply, events, requirements/BOM, branch, agents, app)
  subsystems/ disciplines/  per-part geometry/invariant tests + discipline knowledge tests
  solvers/           kernel/solver tests (cantilever FS, tagged generator, multi-subsystem) — container
scripts/             toolchain_fingerprint.py (the content-address stamp for replay)
docker/              Dockerfile.dev + Dockerfile.app + README (canonical Linux kernel/solver image)
constraints/         kernel-linux.txt (pinned build123d/OCCT/gmsh/CalculiX toolchain)
.devcontainer/       VS Code dev container -> the Linux image
docker-compose.yml   the full wedge stack (backend + worker + Postgres + Redis + frontend) in one command
Makefile             make test | probe | fingerprint | image | ci | ci-determinism | spike4-smoke |
                     seed-catalog
build-plan/          program + phase trackers, spike kill-criteria, findings, reference docs
prd-27-8.14/         the original source PRDs (vision; superseded by build-plan/reference/TECH_PLAN.md)
```

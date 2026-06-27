# Grounded Text-to-CAD

An AI-guided, conversational CAD platform that turns natural-language design intent into
**manufacturable** 3D hardware — built so the LLM proposes, and grounded solvers decide.

- **What we're building & why this way:** [`build-plan/README.md`](build-plan/README.md) (program tracker)
- **Current phase:** Phase 0 — de-risk spikes → [`build-plan/PHASE_0.md`](build-plan/PHASE_0.md)
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
python -m pytest -q                  # 58 passed, 9 skipped (kernel/solver tests skip without the image)
docker run --rm gtc-dev python -m pytest -q   # 67 passed (full: + determinism, FS, sandbox, robustness)
```

Target runtime is Python 3.12; the local floor is 3.10. The kernel/solver/sandbox stack
(build123d, OCCT, Gmsh, CalculiX, Firecracker/gVisor) is **Linux-only** and lives behind the Truth
Plane — see [`build-plan/PHASE_0.md`](build-plan/PHASE_0.md) §3c for the Linux dev container.

## Layout

```
CLAUDE.md            guardrails loaded into every Claude Code session (the 3 inversions + cut-list)
packages/
  ledger/            source of truth: schema, deltas, rules-validator (apply), event store + replay,
                     requirements matrix, BOM/material DB, datum, branching + invariant-aware merge
  interactive_plane/ Tier-0 closed-form proxies (no OCCT/LLM/solver)
  truth_plane/regen/    determinism probe + tagged templated generator (Spike 1 fallback)
  truth_plane/solvers/  validated CalculiX FS pipeline + print estimator (Linux)
  agents/            LLMProvider seam + mock provider + propose→review→commit session + eval harness
  transport/         FastAPI app + two-plane WebSocket protocol (with NACK)
  frontend/          placeholder (React/r3f — not built)
tests/
  acceptance/        pure-Python safety-contract tests
  determinism/       cross-platform B-rep golden gate + mesh probe
  ledger/ backend/   the Phases 1–3 backbone (apply, events, requirements/BOM, branch, agents, app)
  solvers/           kernel/solver tests (cantilever FS, tagged generator) — container
scripts/             toolchain_fingerprint.py (the content-address stamp for replay)
docker/              Dockerfile.dev + README (canonical Linux kernel/solver image; the determinism reference)
constraints/         kernel-linux.txt (pinned build123d/OCCT/gmsh/CalculiX toolchain)
.devcontainer/       VS Code dev container -> the Linux image
Makefile             make test | probe | fingerprint | image | ci | ci-determinism | spike4-smoke
build-plan/          program + phase trackers, spike kill-criteria, findings, reference docs
prd-27-8.14/         the original source PRDs (vision; superseded by build-plan/reference/TECH_PLAN.md)
```

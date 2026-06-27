# Phase 1 — Foundation (Backbone)

**Status:** 🟢 Backbone implemented & tested (production-hardening + sandbox + DB persistence remain)
**Goal:** a hardened, deterministic substrate — only what survived the spikes.

> Scope honesty: this is the *buildable backbone* of Phase 1, implemented in code and green under test.
> It is **not** production-hardened (no DB, no microVM sandbox, in-memory event log). The genuinely
> infra/specialist-gated items are listed under "Remains".

## Done (in code, tested)

| Capability | Module | Tests |
|---|---|---|
| Executable ledger schema (`ParameterDef`, `extra=forbid`, invariants at construction) | `packages/ledger/parameter.py`, `schema.py` | `tests/acceptance/test_export_gates.py` |
| Delta + **rules validator** (clamp / HARD_LOCK / forbidden-target / coupled-invariant→CONFLICT) | `packages/ledger/apply.py`, `deltas.py` | `tests/ledger/test_apply.py` |
| **Event store** (FACTS vs DERIVATIONS, hash-chained, content-addressed) + **pure-fold replay** (never re-invokes LLM/solver) | `packages/ledger/events.py` | `tests/ledger/test_events.py` |
| Export gates (unknown→blocked) + review FSM | `packages/ledger/gates.py`, `schema.py` | `tests/acceptance/test_export_gates.py` |
| **Determinism gate** — B-rep cross-platform golden | `packages/truth_plane/regen/canonical.py` | `tests/determinism/` |
| **One grounded solver** (CalculiX FS, validated vs closed form) | `packages/truth_plane/solvers/` | `tests/solvers/test_fs_cantilever.py` |
| Toolchain fingerprint | `packages/ledger/fingerprint.py` | (used by event store) |
| Generator-deterministic tags (Spike 1 fallback #1) | `packages/truth_plane/regen/templated.py` | `tests/solvers/test_templated_tags.py` |
| **Persistent SQL event store** (sqlite now, Postgres = driver swap; durable across reconnect) | `packages/ledger/event_store_sql.py` | `tests/ledger/test_event_store_sql.py` |
| **Sandbox primitives** — host-side wall-clock SIGKILL of a spinning process + RLIMIT_AS | `packages/truth_plane/sandbox.py` | `tests/backend/test_sandbox.py` |
| **Hero-bracket end-to-end** (generator→FS→estimator→events→export gate flips BLOCKED→ELIGIBLE) | `packages/truth_plane/demo_pipeline.py` | `tests/solvers/test_hero_pipeline.py` |
| Meshing robustness (19/19 auto-mesh) | `packages/truth_plane/solvers/robustness.py` | `tests/solvers/test_mesh_robustness.py` |

## Remains (gated — not buildable solo here)

- **Persistent topological identity** beyond generator tags — geometric-signature backstop + OCAF for
  face-level picking/HUD. → Spike 1, **OCCT engineer** (risk R1).
- **Sandbox isolation** — the kill/RLIMIT *primitives* are built & tested (`sandbox.py`); the full
  isolation boundary (gVisor `runsc` / Firecracker microVM, egress-deny netns, seccomp) is the prod
  deployment wrapper around them — needs runsc/KVM + a security review.
- **Postgres** — the SQL event store runs on sqlite (durable, tested); Postgres is a driver swap over
  the same schema (JSONB/BYTEA). Standing up a live PG + RLS is infra, not in scope here.

# Grounded Text-to-CAD — Codebase Guardrails

This file is loaded into every Claude Code session in this repo. **Read it before writing code.**
Program tracker: `build-plan/README.md`. Architecture: `build-plan/reference/TECH_PLAN.md`.

## The three inversions (NON-NEGOTIABLE — every PR must honor them)

1. **The LLM never originates a safety scalar and never emits free Python.**
   It emits `ParameterDelta` objects (see `packages/ledger/deltas.py`) via strict tool-use ONLY.
   A deterministic Jinja2 + build123d templater renders scripts. Real solvers
   (Gmsh+CalculiX, …) produce every FS / stall / flutter / range number.
   **A missing safety input is `"unknown"` and BLOCKS export — never a fabricated green light.**
2. **The single clock is a fiction — three tiers:**
   - *Interactive plane* (`packages/interactive_plane/`): closed-form arithmetic only, <1 ms/number, 30 Hz. No OCCT, no LLM, no solver.
   - *Kernel regen*: OCCT, debounced to slider-release, async, in the sandbox.
   - *Truth plane* (`packages/truth_plane/`): FEA / slicing / optimization, durable async jobs, minutes-scale, never on the hot path, never re-invoked on replay.
3. **Persistent topological identity** (generator-baked tags + OCAF/TNaming) is the keystone bet.
   Identity is deterministic kernel work — the LLM never touches it.

## DO NOT BUILD (yet) — the cut-list

The wedge is **functional printable/machinable parts** (brackets, mounts, enclosures, fixtures).
Do **not** build, scaffold, or stub any of these without an explicit instruction — each is an
independent multi-month subsystem and pulling one in guarantees we ship nothing:

> flutter / DLM / aeroelasticity · AVL / XFOIL / CFD aero · propulsion / battery / range ·
> kinematics / swept-volume · bonded-joint cohesive FEA · NSGA-II Pareto (use a 3-variant sweep) ·
> ML surrogates / ROM · CRDT multi-user co-edit · semantic branch merge · ITAR / air-gapped vLLM SKU ·
> Kubernetes / KEDA / Temporal / EventStoreDB · Rust core.

Wedge stack: hosted Anthropic API + one FastAPI monolith + Postgres + Redis/Dramatiq +
Firecracker/gVisor + docker-compose on one VM.

## Conventions

- **Typed seams only.** The *only* thing crossing a package boundary is a Pydantic model. No shared
  mutable state, no free dicts. This is what lets parallel subagents work without colliding.
- `extra="forbid"` (≡ `additionalProperties:false`) on every ledger model. Typos must fail loudly.
- **Never weaken a test to make it pass.** A drifted golden hash, a failed convergence, a red gate
  is *signal*. Loosening a tolerance / widening a bound / weakening an assertion to get green is a
  banned move — flag it for human sign-off instead.
- Every LLM call goes through `packages/agents/llm_provider.py::LLMProvider`. Never `import anthropic`
  outside that module (CI lint enforces this — it's the hosted-vs-air-gapped seam).
- Target runtime is Python 3.12 (local dev may be 3.10; keep code 3.10-compatible for now).

## Where Claude needs a human wall (do not self-certify these)

- OCAF/TNaming + OCP FFI — Claude writes fluent code against *phantom* symbols. Plan mode + the
  OCP-introspection MCP + a human OCCT engineer.
- Numerical-determinism debugging (BLAS-thread / FMA / rounding).
- FEA physics correctness — golden values come from handbook / closed-form / PE, never Claude's run.

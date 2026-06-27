# packages/ledger — the single source of truth

This package is the executable spec. **The same Pydantic models are (a) the persisted state, (b) the
runtime tool-use schema for the delta-emitter, and (c) the test fixtures.** Keep it that way.

Hard rules:
- `extra="forbid"` on every model. No bare-number tunables — every adjustable node is a `ParameterDef`.
- `derived.*` and `review.*` are NOT writable by an LLM delta (`deltas.is_forbidden_target`). A
  missing `derived` value is "unknown" and must BLOCK export (`gates.evaluate_export_gates`).
- Bounds/lock invariants live in `ParameterDef` and are enforced at construction. Do not add a code
  path that can build an out-of-bounds or HARD_LOCK-violating parameter.
- No OCCT, no solver, no LLM, no I/O in this package — it is pure data + pure validation.

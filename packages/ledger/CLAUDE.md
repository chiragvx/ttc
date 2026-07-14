# packages/ledger — the single source of truth

This package is the executable spec. **The same Pydantic models are (a) the persisted state, (b) the
runtime tool-use schema for the delta-emitter, and (c) the test fixtures.** Keep it that way.

Hard rules:
- `extra="forbid"` on every model. No bare-number tunables — every adjustable node is a `ParameterDef`.
- `derived.*` and `review.*` are NOT writable by an LLM delta (`deltas.is_forbidden_target`). A
  missing `derived` value is "unknown" and must BLOCK export (`gates.evaluate_export_gates`).
- Lock invariants live in `ParameterDef` and are enforced at construction — do not add a code path
  that can build a HARD_LOCK-violating parameter (`with_value` refuses to mutate one; `apply_delta`
  REJECTs any delta targeting one). `bounds` are ADVISORY, not a hard construction-time clamp
  (2026-07-04 policy — see `parameter.py`/`apply.py`'s own docstrings): a value outside the
  recommended range still constructs and still applies, as `APPLIED_ADVISORY`, on copilot judgment.
  Only HARD_LOCK and physical cross-field invariants (edge-distance, min-wall, cut depth/fit) may
  ever REJECT/CONFLICT a value outright.
- No OCCT, no solver, no LLM, no I/O in this package — it is pure data + pure validation.

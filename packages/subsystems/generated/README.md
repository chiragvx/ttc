# packages/subsystems/generated/ — AI-generated subsystems

This directory holds subsystem files the LLM copilot wrote itself (Phase 0 of the
AI-generated-custom-geometry initiative — `C:\Users\Chirag\.claude\plans\spicy-exploring-cupcake.md`):
genuinely custom build123d geometry that doesn't fit any existing catalog part (their own motivating
example: a bellmouth curve on an EDF intake).

## What happens to a file dropped here

Every `.py` file directly in this directory (this README is skipped — it isn't `.py`) is imported
automatically at server startup by `packages/subsystems/__init__.py::_discover_generated_subsystems()`,
which runs once, after all ~271 hand-authored catalog imports. Each file is expected to be shaped like
any other subsystem module: build a `packages.subsystems.Subsystem` (params, `build`, `volume`,
`invariants`, …) and call `register_subsystem(...)` on it at import time, exactly like every file in
`packages/subsystems/*.py` already does.

A file that fails to import (syntax error, missing required field, raises on load, …) is logged and
skipped — it never crashes server startup and never blocks any other file here from loading.

Same posture as `spur_gear.py` / `lofted_spindle.py`: **`fea_eligible=False`**. A generated subsystem's
`factor_of_safety` honestly stays `"unknown"` — this phase never fabricates a green light.

Every part built from a file here still becomes a real, typed ledger `Instance` — the EKG (typed seams,
`ParameterDelta`s, no free-floating scripts) applies exactly as it does to the rest of the catalog.

## Do not hand-edit files here

Files in this directory are AI-authored and considered disposable/regeneratable — don't hand-maintain
them in place. If a generated subsystem turns out to be genuinely worth keeping permanently, the
intended path (a **later, separate phase of the same initiative — not built yet**) is to *promote/
graduate* it: move (and clean up) the file out of `generated/` into an ordinary hardcoded
`from packages.subsystems import X as _X` import in `packages/subsystems/__init__.py`, alongside the
rest of the catalog. There is no automated promotion mechanism yet — until one exists, graduating a
file is a manual, human-reviewed edit.

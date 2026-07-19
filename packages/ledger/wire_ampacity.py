"""AWG wire ampacity reference — the interface-capacity data ENGINEERING_GRAPH_PLAN.md P3's
rating-check slice needs (packages/couplings' "unknown blocks" doesn't apply here — this is a
capacity CEILING, not a derived load; nothing in this codebase yet compares a coupling's derived
current against it, since no subsystem/coupling represents a wire's carried current — that consuming
gate is a separate, later piece of work, not built here).

Same tier of grounding as `packages/ledger/bom.py::MATERIAL_DB`, deliberately: representative,
rule-of-thumb chassis-wiring (single conductor, free air) ampacity, sourced from the widely-cited
*Handbook of Electronic Tables and Formulas* table (via https://www.powerstream.com/Wire_Size.htm,
2026-07-19) — NOT an NEC-compliance-grade table (that table doesn't cover gauges this small anyway;
NEC 310.16 starts at 14 AWG and assumes conduit/bundling, a different use case). `set_wire_ampacity_db`
(mirrors `set_material_db` exactly) lets `packages/catalog/bootstrap.py::apply_to_live_app()` override
this hardcoded fallback from a real source later; on any failure this dict simply stands, unchanged."""

from __future__ import annotations

# Chassis wiring / single conductor in free air, Amps — a rule of thumb per its own source, not a
# legal/compliance figure. Even AWG sizes only: odd gauges aren't a real wire product to rate.
_DEFAULT_AMPACITY_BY_AWG: dict[str, float] = {
    "AWG30": 0.86,
    "AWG28": 1.4,
    "AWG26": 2.2,
    "AWG24": 3.5,
    "AWG22": 7.0,
    "AWG20": 11.0,
    "AWG18": 16.0,
    "AWG16": 22.0,
    "AWG14": 32.0,
    "AWG12": 41.0,
    "AWG10": 55.0,
}
AMPACITY_BY_AWG: dict[str, float] = dict(_DEFAULT_AMPACITY_BY_AWG)


def ampacity_a(awg: str) -> float:
    key = awg if awg.upper().startswith("AWG") else f"AWG{awg}"
    key = key.upper()
    try:
        return AMPACITY_BY_AWG[key]
    except KeyError as e:
        raise KeyError(f"unknown AWG size {awg!r} (known: {sorted(AMPACITY_BY_AWG)})") from e


def set_wire_ampacity_db(ampacity_by_awg: dict[str, float]) -> None:
    """Override the live ampacity table — the injection point packages/catalog/bootstrap.py uses.
    Pure reassignment, no I/O here (this package's CLAUDE.md forbids it). An empty dict is a
    no-op (never leaves the table empty)."""
    if not ampacity_by_awg:
        return
    global AMPACITY_BY_AWG
    AMPACITY_BY_AWG = dict(ampacity_by_awg)


def reset_wire_ampacity_db() -> None:
    """Restore the hardcoded default — test hygiene, since AMPACITY_BY_AWG is mutable global state a
    test calling set_wire_ampacity_db() must not leak into the next test."""
    global AMPACITY_BY_AWG
    AMPACITY_BY_AWG = dict(_DEFAULT_AMPACITY_BY_AWG)

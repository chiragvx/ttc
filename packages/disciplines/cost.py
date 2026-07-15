"""Cost discipline — a $ readout for the printed part across every subsystem.

Grounding (Inversion #1 still holds):
  * L0 (live now): closed-form estimate — material cost + machine time × rate. Uses the
    deterministic geometry volume from the active subsystem's `volume_mm3(ledger)` and the
    analytic print-time estimate (labeled) already computed by transport telemetry.
  * L1 (later): a real slicer's grounded print time replaces the analytic estimate; material
    prices come from a per-project catalog. Until then, cost is CLEARLY labeled analytic.

The gate is opt-in via `GlobalConstraints.max_cost_usd`: a project can state "under $50" and the
export gate blocks a design that busts it. Without a budget set, cost is a pure readout — no gate
contribution. This is Cost as a lens, not a stopper by default.

2026-07-15 — the per-material $/kg quick-ref and the "cheapest material" callout in the knowledge
fragment now read live packages.ledger.bom.MATERIAL_DB (the same dict
packages/catalog/bootstrap.py::set_material_db() overrides at process startup) instead of a frozen
"PLA/PETG/ABS ≈ $22-25; AL6061 raw ≈ $8; STEEL raw ≈ $2" string — same staleness bug
manufacturing.py's clearance-hole quick-ref had, same fix: the fragment is a CALLABLE, resolved at
PROMPT-BUILD time (packages/disciplines/__init__.py::_fragment_text). `_cost_usd` below already read
MATERIAL_DB live via `material()` — only the prompt TEXT was frozen at import time; this closes that
last gap, so every discipline fragment is catalog-live now.
"""

from __future__ import annotations

from packages.disciplines import register
from packages.disciplines.base import DisciplineSpec, GateFinding
from packages.ledger.bom import material
from packages.ledger.schema import MasterParametricLedger

# Dev-default machine rate (USD/hour) — the hardcoded FALLBACK; `set_machine_rate` (2026-07-15) lets
# packages/catalog/bootstrap.py::apply_to_live_app() override it from the `cost.machine_rates_usd_per_hr`
# reference dataset at process startup (both the API process and the Dramatiq worker process), same
# "hardcoded default, optionally overridden, never crashes on a missing source" shape as
# packages/ledger/bom.py::MATERIAL_DB. At L1 this becomes a per-project param or is derived from a
# per-material/per-process rate table (FDM ≠ CNC ≠ SLA) — the reference dataset already models it as
# a keyed lookup (today's single "fdm_default" entry) for exactly that future expansion.
_DEFAULT_MACHINE_RATE_USD_PER_HR: float = 2.0
MACHINE_RATE_USD_PER_HR: float = _DEFAULT_MACHINE_RATE_USD_PER_HR


def set_machine_rate(rate_usd_per_hr: float) -> None:
    global MACHINE_RATE_USD_PER_HR
    MACHINE_RATE_USD_PER_HR = rate_usd_per_hr


def reset_machine_rate() -> None:
    global MACHINE_RATE_USD_PER_HR
    MACHINE_RATE_USD_PER_HR = _DEFAULT_MACHINE_RATE_USD_PER_HR


def _material_cost_quick_ref() -> str:
    from packages.ledger.bom import MATERIAL_DB

    ordered = sorted(MATERIAL_DB.values(), key=lambda m: m.cost_per_kg_usd)
    return ", ".join(f"{m.name}≈${m.cost_per_kg_usd:g}/kg" for m in ordered)


def _cheapest_material_name() -> str:
    from packages.ledger.bom import MATERIAL_DB

    if not MATERIAL_DB:
        return "the lowest-$/kg option"
    return min(MATERIAL_DB.values(), key=lambda m: m.cost_per_kg_usd).name


def _fragment() -> str:
    return f"""\
## Discipline: Cost (analytic $ estimate — L0)
A pure readout across every part: material cost + machine time × rate. Numbers are ANALYTIC (labeled
as estimates), not slicer-grounded — treat as ballpark, not a quote.
- **material** — material_profile selects a $/kg: {_material_cost_quick_ref()}.
- **mass** — density × geometry volume (deterministic; from the active subsystem's volume function).
- **print/machine time** — the analytic time estimate already used by telemetry (L0); a slicer
  replaces this at L1.
- Budget: set `global_constraints.max_cost_usd` and the export gate blocks any design above it.

### Intent mapping
- "under $N" → set the budget; the copilot proposes lighter/thinner geometry to fit.
- "cheaper material" → propose switching toward the lowest-$/kg option above (today: {_cheapest_material_name()}).
- "reduce mass" → smaller geometry OR switch to a lower-density material (watch the strength trade)."""


def _cost_usd(ledger: MasterParametricLedger) -> float:
    """Closed-form analytic $ = material cost + print time × rate. Deterministic; safe to expose."""
    from packages.subsystems import get_subsystem  # local to avoid discipline↔subsystem circular

    # assembly-wide (2026-07-03): sum every instance's volume once a project holds more than one —
    # matches transport._telemetry's mass summation, so cost doesn't silently under-report the
    # moment a project grows past a single part.
    if not ledger.instances:
        vol_mm3 = 0.0  # empty workspace — nothing built yet, nothing to cost
    elif len(ledger.instances) > 1:
        vol_mm3 = 0.0
        for iid, inst in ledger.instances.items():
            sub = get_subsystem(inst.subsystem_type)
            vol_mm3 += sub.volume_mm3(ledger, iid) if sub.volume_mm3 is not None else 0.0
    else:
        # exactly one instance in the file (2026-07-04: parts are a flat set, no root) — read its
        # OWN subsystem_type directly, not the stale project_metadata compat field (which tracks
        # nothing once a file is built up via instance_ops rather than the old genesis path).
        only = next(iter(ledger.instances.values()))
        sub = get_subsystem(only.subsystem_type)
        vol_mm3 = sub.volume_mm3(ledger, only.id) if sub.volume_mm3 is not None else 0.0
    mat = material(ledger.domains.structure.material_profile)
    mass_kg = mat.density_g_per_mm3 * vol_mm3 / 1000.0
    material_cost = mass_kg * mat.cost_per_kg_usd

    # analytic print-time estimate (same shape as transport._telemetry uses)
    print_time_hr = (vol_mm3 / 5.0) / 3600.0
    time_cost = print_time_hr * MACHINE_RATE_USD_PER_HR

    return material_cost + time_cost


def _gate(ledger: MasterParametricLedger) -> GateFinding:
    budget = ledger.global_constraints.max_cost_usd
    if budget is None:
        return GateFinding()  # no budget stated → pure readout, no gate contribution
    cost = _cost_usd(ledger)
    if cost > budget:
        return GateFinding(reasons=[
            f"estimated cost ${cost:.2f} exceeds max_cost_usd ${budget:.2f} — "
            f"reduce geometry or switch material"])
    return GateFinding()


COST = register(DisciplineSpec(
    name="cost",
    description="Analytic $ readout (material + machine time × rate); optional max_cost_usd gate",
    knowledge_fragment=_fragment,  # callable — see this module's docstring
    # Cost applies to every part regardless of ledger contents — it reads whatever active subsystem
    # is set + material_profile from the structure discipline block.
    # No owned params (uses shared discipline data + subsystem volume).
    evaluate_gate=_gate,
))


# Public helper for other modules (telemetry, tests) that want the current cost estimate.
def cost_usd(ledger: MasterParametricLedger) -> float:
    return _cost_usd(ledger)

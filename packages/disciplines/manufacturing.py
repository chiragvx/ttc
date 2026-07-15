"""Manufacturing / DFM discipline — printability & assembly lens.

The min-wall floor and watertight/min_wall gates live in the core validator (apply.py) + export gates
(gates.py); this spec owns the params + DFM reasoning, not a duplicate check.

2026-07-15 — the clearance-hole quick-ref and the advisory "recommended" wall thickness are now
sourced from packages/catalog (a hardcoded fallback stands if no catalog data is available — same
"never crash, never go silent" shape as packages/ledger/bom.py::set_material_db). The knowledge
fragment is a CALLABLE now, not a frozen string, so it reflects whatever is live at PROMPT-BUILD time
(see packages/disciplines/__init__.py::_fragment_text). The HARD min-wall FLOOR quoted in the prompt
is deliberately NOT sourced from the catalog — it reads packages.ledger.apply.MIN_WALL_MM directly,
the single constant that's actually ENFORCED, so the prompt can never claim a floor that doesn't
match what export gating really checks (the catalog's own copy of this number is informational only,
for a future reference-data consumer, not a second source of truth for enforcement).
"""

from __future__ import annotations

from packages.disciplines import register
from packages.disciplines.base import DisciplineSpec
from packages.ledger.nodes import BUILD_ORIENTATION, HOLE_DIA, SLIP_FIT

_DEFAULT_CLEARANCE_HOLES_MM: dict[str, float] = {"M3": 3.4, "M4": 4.5, "M5": 5.4, "M6": 6.4, "M8": 8.4}
_DEFAULT_RECOMMENDED_WALL_MM: float = 1.2

_clearance_holes_mm: dict[str, float] = dict(_DEFAULT_CLEARANCE_HOLES_MM)
_recommended_wall_mm: float = _DEFAULT_RECOMMENDED_WALL_MM


def set_dfm_reference(*, clearance_holes_mm: "dict[str, float] | None" = None,
                      recommended_wall_mm: "float | None" = None) -> None:
    """The injection point packages/catalog/bootstrap.py uses. Either argument may be omitted (only
    override what the caller actually has data for); an empty/None clearance_holes_mm is a no-op,
    same as packages/ledger/bom.py::set_material_db's "never leave the catalog empty" contract."""
    global _clearance_holes_mm, _recommended_wall_mm
    if clearance_holes_mm:
        _clearance_holes_mm = dict(clearance_holes_mm)
    if recommended_wall_mm is not None:
        _recommended_wall_mm = recommended_wall_mm


def reset_dfm_reference() -> None:
    global _clearance_holes_mm, _recommended_wall_mm
    _clearance_holes_mm = dict(_DEFAULT_CLEARANCE_HOLES_MM)
    _recommended_wall_mm = _DEFAULT_RECOMMENDED_WALL_MM


def _clearance_holes_quick_ref() -> str:
    def _sort_key(item: tuple[str, float]) -> tuple[int, object]:
        name, _ = item
        digits = "".join(c for c in name if c.isdigit())
        return (0, int(digits)) if digits else (1, name)
    ordered = sorted(_clearance_holes_mm.items(), key=_sort_key)
    return ", ".join(f"{name}→{val:g}" for name, val in ordered)


def _fragment() -> str:
    from packages.ledger.apply import MIN_WALL_MM  # the ACTUAL enforced constant, not a catalog copy

    return f"""\
## Discipline: Manufacturing / DFM (printability & fit)
Governs whether the part can actually be made. Rules for FDM/FFF unless the material is metal (then CNC).
- **build_orientation_deg** — 0° = flat (no supports, weakest in Z); 90° = on edge (strongest in-plane,
  overhangs > 45° may need supports). Prototypes ⇒ 0°; load-bearing ⇒ 45°–90°.
- **slip_fit_clearance_mm** — 0.2 mm standard FDM; 0.1 mm press-fit; 0.3–0.5 mm easy slip-in.
- **hole_diameter_mm** — clearance-hole quick ref: {_clearance_holes_quick_ref()}. Tapped
  (heat-set insert) ⇒ use the insert OD, not the bolt clearance.
- Minimum wall is {MIN_WALL_MM:g} mm (hard floor, enforced); ≥ {_recommended_wall_mm:g} mm recommended for load-bearing."""


MANUFACTURING = register(DisciplineSpec(
    name="manufacturing",
    description="Printability & assembly fit — DFM rules + slicer cost",
    knowledge_fragment=_fragment,  # callable — see this module's docstring
    owned_params=(BUILD_ORIENTATION, SLIP_FIT, HOLE_DIA),
    geometry_params=(HOLE_DIA,),  # hole size changes the FEA stress field; orientation/fit do not
))

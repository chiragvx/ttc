"""Manufacturing / DFM discipline — printability & assembly lens.

The min-wall floor and watertight/min_wall gates live in the core validator (apply.py) + export gates
(gates.py); this spec owns the params + DFM reasoning, not a duplicate check.
"""

from __future__ import annotations

from packages.disciplines import register
from packages.disciplines.base import DisciplineSpec
from packages.ledger.nodes import BUILD_ORIENTATION, HOLE_DIA, SLIP_FIT

_FRAGMENT = """\
## Discipline: Manufacturing / DFM (printability & fit)
Governs whether the part can actually be made. Rules for FDM/FFF unless the material is metal (then CNC).
- **build_orientation_deg** — 0° = flat (no supports, weakest in Z); 90° = on edge (strongest in-plane,
  overhangs > 45° may need supports). Prototypes ⇒ 0°; load-bearing ⇒ 45°–90°.
- **slip_fit_clearance_mm** — 0.2 mm standard FDM; 0.1 mm press-fit; 0.3–0.5 mm easy slip-in.
- **hole_diameter_mm** — clearance-hole quick ref: M3→3.4, M4→4.5, M5→5.4, M6→6.4, M8→8.4. Tapped
  (heat-set insert) ⇒ use the insert OD, not the bolt clearance.
- Minimum wall is 0.8 mm (hard floor, enforced); ≥ 1.2 mm recommended for load-bearing."""

MANUFACTURING = register(DisciplineSpec(
    name="manufacturing",
    description="Printability & assembly fit — DFM rules + slicer cost",
    knowledge_fragment=_FRAGMENT,
    owned_params=(BUILD_ORIENTATION, SLIP_FIT, HOLE_DIA),
    geometry_params=(HOLE_DIA,),  # hole size changes the FEA stress field; orientation/fit do not
))

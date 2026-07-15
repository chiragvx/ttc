"""Structures discipline — load-bearing strength & stiffness lens.

Formalizes what was implicit: the params, knowledge, and gate that govern structural integrity. The
factor-of-safety scalar itself comes from the Gmsh+CalculiX solver via the core export gates
(gates.py) + derived_resolver — this spec does NOT duplicate that; it owns the reasoning + params.

2026-07-15 — the "suggest a stiffer material" callout now names whatever is actually stiffest in the
live packages.ledger.bom.MATERIAL_DB (the same dict packages/catalog/bootstrap.py::set_material_db()
overrides at process startup) instead of a frozen "AL6061/STEEL" string, so it can never cite a
material the catalog no longer has loaded. The knowledge fragment is a CALLABLE now, resolved at
PROMPT-BUILD time (see packages/disciplines/__init__.py::_fragment_text) — same pattern
manufacturing.py established for its clearance-hole quick-ref.
"""

from __future__ import annotations

from packages.disciplines import register
from packages.disciplines.base import DisciplineSpec
from packages.ledger.nodes import DEPTH, MATERIAL, RIB, SKIN, WIDTH


def _stiffer_material_names() -> str:
    from packages.ledger.bom import MATERIAL_DB

    ordered = sorted(MATERIAL_DB.values(), key=lambda m: m.youngs_mod_mpa, reverse=True)
    names = [m.name for m in ordered[:2]]
    return "/".join(names) if names else "a stiffer material"


def _fragment() -> str:
    return f"""\
## Discipline: Structures (strength & stiffness)
Governs whether the part survives its declared load. The factor-of-safety (FS) is produced by
Gmsh + CalculiX FEA — never by you. Export is blocked until FS ≥ floor with a converged mesh.
- **skin_thickness_mm** — primary strength lever; peak stress ∝ 1/t². "Stronger"/"higher FS" ⇒ raise it
  first. At its upper bound ⇒ suggest a stiffer material ({_stiffer_material_names()}).
- **internal_rib_spacing_mm** — bending stiffness. Smaller = stiffer & heavier; larger = lighter (then
  re-run the optimize sweep for the minimum passing skin).
- **plate_width_mm × plate_depth_mm** — footprint; larger spreads load & lowers bearing stress at holes.
- **material_profile** — trades stiffness (E) and yield (σ_y) against density. Never invent allowables;
  they come from the solver's material DB."""


STRUCTURES = register(DisciplineSpec(
    name="structures",
    description="Load-bearing strength & stiffness — FS from Gmsh+CalculiX",
    knowledge_fragment=_fragment,  # callable — see this module's docstring
    owned_params=(MATERIAL, SKIN, RIB, WIDTH, DEPTH),
    geometry_params=(SKIN, RIB, WIDTH, DEPTH),
    # FS / mesh gates live in the core export gates (gates.py); no duplication here.
))

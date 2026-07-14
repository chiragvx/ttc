"""Mounting bracket subsystem — new-style (Phase D). Flat plate + a row of bolt holes."""

from __future__ import annotations

from packages.subsystems import ParamSpec, Subsystem, register_subsystem

_FRAGMENT = """\
## Subsystem: Mounting Bracket
A flat plate with a row of bolt holes, carrying a declared transverse load. Geometry params:
- **skin_thickness_mm** — plate thickness (the strength lever; see the Structures discipline).
- **internal_rib_spacing_mm** — rib pitch across the plate (stiffness vs mass).
- **plate_width_mm × plate_depth_mm** — the mounting footprint.
- **hole_diameter_mm** — bolt-hole size (edge-distance rule: hole_dia ≤ plate_depth / 3, enforced).

### Fastener clearance-hole quick reference
M3→3.4 · M4→4.5 · M5→5.4 · M6→6.4 · M8→8.4 · #10→5.0 mm. Tapped/heat-set inserts: use the insert OD.

### Intent mapping (bracket-specific geometry moves)
- "smaller"/"compact"/"fits in N mm" → reduce **plate_width_mm** and/or **plate_depth_mm** (warn if
  hole edge distance goes marginal). Ask which axis if unclear.
- "M6 bolts" → **hole_diameter_mm** = 6.4; "tapped M6" → 5.0.
- For strength/stiffness/mass/printability moves, follow the Structures & Manufacturing disciplines.\
"""


def _build(p):
    from packages.truth_plane.regen.templated import render_bracket
    return render_bracket(width_mm=p.plate_width_mm, depth_mm=p.plate_depth_mm,
                          thickness_mm=max(1.0, p.skin_thickness_mm),
                          hole_dia_mm=p.hole_diameter_mm, n_holes=int(p.hole_count))


def _volume(p) -> float:
    return p.plate_width_mm * p.plate_depth_mm * p.skin_thickness_mm


def _check(p) -> list[str]:
    # 1.5× edge-distance rule: hole_dia ≤ plate_depth / 3
    max_dia = p.plate_depth_mm / 3.0
    if p.hole_diameter_mm > max_dia:
        return [f"hole_diameter {p.hole_diameter_mm:.1f} mm exceeds plate_depth/3 "
                f"({max_dia:.1f} mm) — edge distance < 1.5× dia violates bolted-joint rule"]
    return []


def _cascade(ledger, target_node, requested_value):
    """prd-27-8.14/prd4.md §2.2's cascade example, applied here: when a bigger bolt hole would
    violate the edge-distance rule (hole_dia ≤ plate_depth/3), grow plate_depth_mm to the minimum
    value that keeps the rule satisfied — instead of outright rejecting the request. Soft bounds
    already stopped rejecting a hole_diameter_mm outside its own recommended range (2026-07-03,
    APPLIED_ADVISORY); this closes the same "cat-mouse" gap for the edge-distance INVARIANT, which
    previously CONFLICTed no matter how reasonable the request (e.g. a 15mm/M12 hole)."""
    if not target_node.endswith(".hole_diameter_mm"):
        return []
    from packages.ledger.apply import resolve_path
    depth_path = f"{target_node.rsplit('.', 1)[0]}.plate_depth_mm"
    depth_pd = resolve_path(ledger, depth_path)
    if depth_pd is None:
        return []
    needed_depth = requested_value * 3.0
    if needed_depth <= depth_pd.value:
        return []  # the current depth already satisfies the rule — no cascade needed
    return [(depth_path, needed_depth,
            f"grew plate_depth_mm to {needed_depth:.1f} mm to keep the edge-distance rule "
            f"(hole_dia ≤ depth/3) satisfied for a {requested_value:.1f} mm hole")]


BRACKET = register_subsystem(Subsystem(
    name="bracket",
    description="Flat-plate mounting bracket with bolt holes — FDM/FFF or CNC machined",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing", "thermal"),
    params=[
        ParamSpec("skin_thickness_mm",       value=2.0,  min=1.0,  max=5.0,   unit="mm"),
        ParamSpec("internal_rib_spacing_mm", value=20.0, min=10.0, max=50.0,  unit="mm"),
        ParamSpec("plate_width_mm",          value=60.0, min=40.0, max=120.0, unit="mm"),
        ParamSpec("plate_depth_mm",          value=40.0, min=30.0, max=80.0,  unit="mm"),
        ParamSpec("hole_diameter_mm",        value=6.0,  min=3.0,  max=10.0,  unit="mm"),
        ParamSpec("hole_count",              value=4,    min=1,    max=12,    unit="count"),
    ],
    build=_build,
    volume=_volume,
    invariants=_check,
    fea_eligible=True,  # the original validated cantilever case (single box, holes inset from X ends)
    cascades=_cascade,
))

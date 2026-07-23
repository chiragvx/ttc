"""Enclosure — a hollow box + a matching lid, as ONE design (produces two printed parts).

This is one subsystem, not two: a single param block drives both bodies so the lid always fits the
box by construction. The geometry builder returns a compound (box shell + lid, positioned side by
side above the print bed) so the viewport + STEP export show both parts.

Why merged: box + lid is one design intent. Splitting them would force the user to keep
`enclosure.box_width_mm` and `box_lid.outer_width_mm` in sync manually — that's the coupling this
axis is supposed to eliminate.
"""

from __future__ import annotations

from packages.subsystems import ParamSpec, Subsystem, box_face_interfaces, register_subsystem

_MIN_WALL_MM = 0.8

_FRAGMENT = """\
## Subsystem: Enclosure (box + matching lid)
One design → two printed parts (box shell + lid). The single param block guarantees the lid fits the
box by construction (matched outer dims; lip fits the interior with `lid_clearance_mm` slip).
- **box_width_mm × box_depth_mm × box_height_mm** — external box envelope.
- **wall_thickness_mm** — box shell wall + floor thickness (also used for the lid lip wall).
- **lid_thickness_mm** — lid top-plate thickness.
- **lid_lip_height_mm** — how deep the lid's downward lip drops into the box opening.
- **lid_clearance_mm** — slip fit between the lid lip's outer face and the box's interior wall.

### Intent mapping
- "fits a [W]×[D] board" → box_width/box_depth ≈ board + 2×wall + wire clearance.
- "taller"/"deeper case" → increase **box_height_mm**.
- "thinner walls"/"lighter" → decrease **wall_thickness_mm** (watch 0.8 mm floor).
- "lid too tight"/"too loose" → adjust **lid_clearance_mm** (0.2 mm snug, 0.4 mm easy).
- "no lid needed" → set **lid_lip_height_mm** small and **lid_thickness_mm** near the min.\
"""


def _build(p):
    import build123d as bd
    from packages.truth_plane.regen.templated import TaggedPart

    # --- box shell (open top) ---
    outer = bd.Box(p.box_width_mm, p.box_depth_mm, p.box_height_mm)
    inner_w = p.box_width_mm - 2.0 * p.wall_thickness_mm
    inner_d = p.box_depth_mm - 2.0 * p.wall_thickness_mm
    inner_h = p.box_height_mm - p.wall_thickness_mm
    cavity = bd.Pos(0.0, 0.0, p.wall_thickness_mm / 2.0 + 0.5) \
             * bd.Box(max(0.1, inner_w), max(0.1, inner_d), inner_h + 1.0)
    box_shell = outer - cavity

    # --- lid placed next to the box on the print bed (in +Y direction) ---
    lid_gap = 10.0  # visual separation so the two parts are clearly distinct
    lid_y = p.box_depth_mm / 2.0 + lid_gap + p.box_depth_mm / 2.0
    # lid plate has the SAME outer footprint as the box (they mate face-to-face)
    lid_plate = bd.Pos(0.0, lid_y, p.lid_lip_height_mm + p.lid_thickness_mm / 2.0) \
                * bd.Box(p.box_width_mm, p.box_depth_mm, p.lid_thickness_mm)
    # downward lip drops from the lid plate into the box opening (outer face = box interior − clearance)
    lip_outer_w = max(0.1, inner_w - 2.0 * p.lid_clearance_mm)
    lip_outer_d = max(0.1, inner_d - 2.0 * p.lid_clearance_mm)
    lip_inner_w = max(0.1, lip_outer_w - 2.0 * p.wall_thickness_mm)
    lip_inner_d = max(0.1, lip_outer_d - 2.0 * p.wall_thickness_mm)
    lip_outer_solid = bd.Pos(0.0, lid_y, p.lid_lip_height_mm / 2.0) \
                      * bd.Box(lip_outer_w, lip_outer_d, p.lid_lip_height_mm)
    lip_cavity = bd.Pos(0.0, lid_y, p.lid_lip_height_mm / 2.0) \
                 * bd.Box(lip_inner_w, lip_inner_d, p.lid_lip_height_mm + 1.0)
    lid = lid_plate + (lip_outer_solid - lip_cavity)

    return TaggedPart(box_shell + lid, {
        # legacy tags kept for continuity with prior tests
        "shell.body": {"kind": "solid", "size": [p.box_width_mm, p.box_depth_mm, p.box_height_mm]},
        "cavity.void": {"kind": "pocket", "size": [inner_w, inner_d, inner_h]},
        # new lid tags — this subsystem now produces the lid as a separate body in the compound
        "lid.plate": {"kind": "solid",
                      "size": [p.box_width_mm, p.box_depth_mm, p.lid_thickness_mm]},
        "lid.lip":   {"kind": "solid",
                      "outer": [lip_outer_w, lip_outer_d], "height": p.lid_lip_height_mm},
    })


def _volume(p):
    # box shell (outer − cavity)
    box_outer_v = p.box_width_mm * p.box_depth_mm * p.box_height_mm
    inner_w = max(0.0, p.box_width_mm - 2.0 * p.wall_thickness_mm)
    inner_d = max(0.0, p.box_depth_mm - 2.0 * p.wall_thickness_mm)
    inner_h = max(0.0, p.box_height_mm - p.wall_thickness_mm)
    box_shell_v = box_outer_v - inner_w * inner_d * inner_h

    # lid plate
    lid_plate_v = p.box_width_mm * p.box_depth_mm * p.lid_thickness_mm

    # lid lip (hollow rectangular ring)
    lip_outer_w = max(0.0, inner_w - 2.0 * p.lid_clearance_mm)
    lip_outer_d = max(0.0, inner_d - 2.0 * p.lid_clearance_mm)
    lip_inner_w = max(0.0, lip_outer_w - 2.0 * p.wall_thickness_mm)
    lip_inner_d = max(0.0, lip_outer_d - 2.0 * p.wall_thickness_mm)
    lip_v = (lip_outer_w * lip_outer_d - lip_inner_w * lip_inner_d) * p.lid_lip_height_mm

    return box_shell_v + lid_plate_v + lip_v


def _check(p):
    out: list[str] = []
    if p.wall_thickness_mm < _MIN_WALL_MM:
        out.append(f"wall_thickness {p.wall_thickness_mm:.2f} mm < min wall {_MIN_WALL_MM} mm")
    if p.lid_thickness_mm < _MIN_WALL_MM:
        out.append(f"lid_thickness {p.lid_thickness_mm:.2f} mm < min wall {_MIN_WALL_MM} mm")
    if 2 * p.wall_thickness_mm >= min(p.box_width_mm, p.box_depth_mm):
        out.append(f"wall_thickness ×2 leaves no cavity in a "
                   f"{p.box_width_mm:.0f}×{p.box_depth_mm:.0f} mm box")
    if p.wall_thickness_mm >= p.box_height_mm:
        out.append(f"wall_thickness {p.wall_thickness_mm:.2f} mm ≥ box_height {p.box_height_mm:.0f} mm")
    # lid lip must have positive wall
    inner_w = p.box_width_mm - 2 * p.wall_thickness_mm
    lip_outer_w = inner_w - 2 * p.lid_clearance_mm
    if lip_outer_w - 2 * p.wall_thickness_mm <= 0:
        out.append("lid lip has no wall — reduce lid_clearance or grow the box")
    return out


ENCLOSURE = register_subsystem(Subsystem(
    name="enclosure",
    description="Hollow box + matching lid (one design → two printed parts)",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing", "thermal"),
    params=[
        ParamSpec("box_width_mm",       value=80.0, min=40.0, max=200.0, unit="mm"),
        ParamSpec("box_depth_mm",       value=60.0, min=30.0, max=200.0, unit="mm"),
        ParamSpec("box_height_mm",      value=40.0, min=10.0, max=150.0, unit="mm"),
        ParamSpec("wall_thickness_mm",  value=2.0,  min=0.8,  max=6.0,   unit="mm"),
        ParamSpec("lid_thickness_mm",   value=2.0,  min=0.8,  max=8.0,   unit="mm"),
        ParamSpec("lid_lip_height_mm",  value=5.0,  min=1.0,  max=20.0,  unit="mm"),
        ParamSpec("lid_clearance_mm",   value=0.2,  min=0.0,  max=1.0,   unit="mm"),
    ],
    build=_build,
    volume=_volume,
    invariants=_check,
    interfaces=box_face_interfaces("box_width_mm", "box_depth_mm", "box_height_mm"),  # 2026-07-22
))

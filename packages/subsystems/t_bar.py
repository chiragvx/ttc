"""T-bar — extruded T cross-section (web + flange)."""

from __future__ import annotations

from packages.subsystems import InterfaceSpec, ParamSpec, Subsystem, register_subsystem

_FRAGMENT = """\
## Subsystem: T-bar
An extruded T cross-section — a stiffened rail.
- **length_mm** — extrusion length.
- **flange_width_mm × flange_thickness_mm** — the top of the T (crossbar).
- **web_height_mm × web_thickness_mm** — the vertical stem.\
"""

_MIN_WALL_MM = 0.8


def _build(p):
    import build123d as bd
    from packages.truth_plane.regen.templated import TaggedPart
    # flange (crossbar) sits on top; web hangs below
    flange = bd.Pos(0.0, 0.0, p.web_height_mm + p.flange_thickness_mm / 2.0) \
             * bd.Box(p.length_mm, p.flange_width_mm, p.flange_thickness_mm)
    web = bd.Pos(0.0, 0.0, p.web_height_mm / 2.0) \
          * bd.Box(p.length_mm, p.web_thickness_mm, p.web_height_mm)
    return TaggedPart(flange + web, {
        "flange.body": {"kind": "solid"},
        "web.body": {"kind": "solid"},
    })


def _volume(p):
    return p.length_mm * (p.flange_width_mm * p.flange_thickness_mm
                          + p.web_thickness_mm * p.web_height_mm)


def _check(p):
    out = []
    if min(p.flange_thickness_mm, p.web_thickness_mm) < _MIN_WALL_MM:
        out.append(f"a thickness < min wall {_MIN_WALL_MM} mm")
    if p.web_thickness_mm >= p.flange_width_mm:
        out.append("web wider than flange — degenerate T")
    return out


def _end_a(p):
    """Local mate frame at the extrusion's -X end. `_build` centers BOTH boxes on local X (no X offset
    in either `bd.Pos` call) and on local Y, so the length axis matches `bar_end_interfaces`'s own
    assumption -- but NOT on local Z: the web spans z=0..web_height_mm and the flange sits on top of
    it (z=web_height_mm..+flange_thickness_mm), so the T cross-section's real vertical extent is
    [0, web_height_mm+flange_thickness_mm], not symmetric about z=0 like a plain centered box. Using
    `bar_end_interfaces` as-is would silently place the mount origin at z=0 -- the web's bottom edge,
    not the end face's real center -- so this frame instead uses the cross-section's actual vertical
    midpoint, same "compute the real coordinate" approach as `locating_pin`'s base_face/nose_face and
    `hex_bar`'s end_a/end_b. Outward normal is -X."""
    from packages.subsystems.base import Frame
    half = p.length_mm / 2.0
    z_mid = (p.web_height_mm + p.flange_thickness_mm) / 2.0
    return Frame(origin=(-half, 0.0, z_mid), normal=(-1.0, 0.0, 0.0))


def _end_b(p):
    """Local mate frame at the extrusion's +X end -- mirror of `_end_a`. Outward normal is +X."""
    from packages.subsystems.base import Frame
    half = p.length_mm / 2.0
    z_mid = (p.web_height_mm + p.flange_thickness_mm) / 2.0
    return Frame(origin=(half, 0.0, z_mid), normal=(1.0, 0.0, 0.0))


T_BAR = register_subsystem(Subsystem(
    name="t_bar",
    description="Extruded T cross-section — structural rail",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing", "thermal"),
    params=[
        ParamSpec("length_mm",           value=100.0, min=20.0, max=500.0, unit="mm"),
        ParamSpec("flange_width_mm",     value=30.0,  min=8.0,  max=120.0, unit="mm"),
        ParamSpec("flange_thickness_mm", value=3.0,   min=0.8,  max=15.0,  unit="mm"),
        ParamSpec("web_height_mm",       value=20.0,  min=5.0,  max=100.0, unit="mm"),
        ParamSpec("web_thickness_mm",    value=3.0,   min=0.8,  max=15.0,  unit="mm"),
    ],
    build=_build, volume=_volume, invariants=_check,
    # 2026-07-28 (interface-coverage sweep, final wave): the length axis (X) is centered like the
    # `bar_end_interfaces` family assumes, but the T cross-section is NOT centered on Z (web sits
    # z=0..web_height_mm, flange stacked above it) -- bespoke frames computed from the part's own real
    # vertical midpoint instead. See `_end_a`'s docstring for the full reasoning.
    interfaces=[
        InterfaceSpec(name="end_a", kind="mount", frame=_end_a),
        InterfaceSpec(name="end_b", kind="mount", frame=_end_b),
    ],
))

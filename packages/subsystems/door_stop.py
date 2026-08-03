"""Door Stop -- Wedge + fastener boss (fastener boss not modeled)

Structural/mounting geometry only (`build-plan/reference/SUBSYSTEM_PROPOSALS.md` category
2) -- a linearly-tapered wedge: a loft between two rectangular cross-sections of different
heights at each end of the length.
"""

from __future__ import annotations

from packages.subsystems import InterfaceSpec, ParamSpec, Subsystem, register_subsystem

_MIN_WALL_MM = 0.8

_FRAGMENT = """\
## Subsystem: Door Stop
Wedge + fastener boss (fastener boss not modeled) -- a linearly-tapered wedge (FDM/FFF or CNC).
- **length_mm** -- taper direction.
- **width_mm** -- constant width.
- **height_a_mm / height_b_mm** -- thickness at each end (may be equal for an untapered plate).\
"""


def _build(p):
    import build123d as bd
    from packages.truth_plane.regen.templated import TaggedPart
    sec_a = bd.Pos(-p.length_mm / 2.0, 0, 0) * bd.Rotation(0, 90, 0) * bd.Rectangle(p.height_a_mm, p.width_mm)
    sec_b = bd.Pos(p.length_mm / 2.0, 0, 0) * bd.Rotation(0, 90, 0) * bd.Rectangle(p.height_b_mm, p.width_mm)
    body = bd.loft([sec_a, sec_b], ruled=True)
    return TaggedPart(body, {"wedge.body": {"kind": "solid", "length": p.length_mm, "width": p.width_mm}})


def _volume(p) -> float:
    return p.length_mm * p.width_mm * (p.height_a_mm + p.height_b_mm) / 2.0


def _check(p) -> list[str]:
    if min(p.height_a_mm, p.height_b_mm) < _MIN_WALL_MM:
        return [f"thinnest end {min(p.height_a_mm, p.height_b_mm):.2f} mm < min wall {_MIN_WALL_MM} mm"]
    return []


def _heel_face(p):
    """Local mate frame at the wedge's THICK end -- `_build` lofts `sec_a` (cross-section
    height_a_mm x width_mm) at x=-length_mm/2, ruled straight to `sec_b` at x=+length_mm/2, and both
    `Rectangle`s are centered on the origin by construction -- so this face's center sits exactly at
    (-length_mm/2, 0, 0) regardless of the (different) height at each end, unlike `bar_end_interfaces`
    which assumes a UNIFORM cross-section box. Outward normal is -X (this is the door stop's back/
    heel, the tall end that sits proud of the floor)."""
    from packages.subsystems.base import Frame
    return Frame(origin=(-p.length_mm / 2.0, 0.0, 0.0), normal=(-1.0, 0.0, 0.0))


def _toe_face(p):
    """Local mate frame at the wedge's THIN end -- same construction as `_heel_face` but at
    x=+length_mm/2. This is the door stop's toe/tip (the low, thin end that slides under the door),
    outward normal +X."""
    from packages.subsystems.base import Frame
    return Frame(origin=(p.length_mm / 2.0, 0.0, 0.0), normal=(1.0, 0.0, 0.0))


DOOR_STOP = register_subsystem(Subsystem(
    name="door_stop",
    description="Wedge + fastener boss -- structural/mounting geometry (FDM/FFF or CNC)",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing", "thermal"),
    params=[
        ParamSpec("length_mm", value=40.0, min=12.0, max=120.0, unit='mm'),
        ParamSpec("width_mm", value=25.0, min=8.0, max=80.0, unit='mm'),
        ParamSpec("height_a_mm", value=25.0, min=6.0, max=80.0, unit='mm'),
        ParamSpec("height_b_mm", value=3.0, min=1.0, max=15.0, unit='mm'),
    ],
    build=_build,
    volume=_volume,
    invariants=_check,
    # 2026-07-28 (interface-coverage sweep, final wave): a linearly-tapered wedge (`bd.loft` between
    # two DIFFERENT-height rectangular sections), not a uniform-cross-section box -- `bar_end_interfaces`
    # doesn't fit its docstring contract (it assumes a plain `bd.Box`), so bespoke frames instead. Both
    # `Rectangle`s are centered on the origin in Y/Z, so each end face's center still lands exactly on
    # the local X axis at +/-length_mm/2 despite the taper -- `heel_face` (thick end) and `toe_face`
    # (thin end) computed straight from that construction.
    interfaces=[
        InterfaceSpec(name="heel_face", kind="mount", frame=_heel_face),
        InterfaceSpec(name="toe_face", kind="mount", frame=_toe_face),
    ],
))

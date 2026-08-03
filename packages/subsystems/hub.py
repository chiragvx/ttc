"""Hub — stepped-diameter cylinder with a central through-bore (a boss for gears/pulleys)."""

from __future__ import annotations

import math

from packages.subsystems import InterfaceSpec, ParamSpec, Subsystem, register_subsystem

_FRAGMENT = """\
## Subsystem: Hub
A stepped cylinder — a wide base disc for mounting features (gears, pulleys, wheels) plus a narrower
boss extending along the shaft axis. Central through-bore for the shaft.
- **disc_dia_mm × disc_thickness_mm** — the wide base disc.
- **boss_dia_mm × boss_height_mm** — the narrower cylindrical boss (sits atop the disc).
- **bore_dia_mm** — through-bore for the shaft.\
"""

_MIN_WALL_MM = 0.8


def _build(p):
    import build123d as bd
    from packages.truth_plane.regen.templated import TaggedPart
    disc = bd.Cylinder(radius=p.disc_dia_mm / 2.0, height=p.disc_thickness_mm)
    boss = bd.Pos(0.0, 0.0, p.disc_thickness_mm / 2.0 + p.boss_height_mm / 2.0) \
           * bd.Cylinder(radius=p.boss_dia_mm / 2.0, height=p.boss_height_mm)
    part = disc + boss
    total_h = p.disc_thickness_mm + p.boss_height_mm
    part = part - bd.Cylinder(radius=p.bore_dia_mm / 2.0, height=total_h * 2.0)
    return TaggedPart(part, {
        "disc.body": {"kind": "solid", "dia": p.disc_dia_mm, "h": p.disc_thickness_mm},
        "boss.body": {"kind": "solid", "dia": p.boss_dia_mm, "h": p.boss_height_mm},
        "bore.thru": {"kind": "cyl_bore", "dia": p.bore_dia_mm},
    })


def _volume(p):
    disc = math.pi * (p.disc_dia_mm / 2.0) ** 2 * p.disc_thickness_mm
    boss = math.pi * (p.boss_dia_mm / 2.0) ** 2 * p.boss_height_mm
    bore = math.pi * (p.bore_dia_mm / 2.0) ** 2 * (p.disc_thickness_mm + p.boss_height_mm)
    return max(0.0, disc + boss - bore)


def _check(p):
    out = []
    if p.bore_dia_mm >= p.boss_dia_mm - 2 * _MIN_WALL_MM:
        out.append(f"boss wall < {_MIN_WALL_MM} mm — grow boss_dia or shrink bore_dia")
    if p.boss_dia_mm >= p.disc_dia_mm - 2 * _MIN_WALL_MM:
        out.append("boss reaches disc edge — grow the disc")
    return out


def _disc_face(p):
    """Local mate frame at the disc's bottom face — z = -disc_thickness_mm/2 by construction (`_build`
    puts the disc `bd.Cylinder(...)` UNROTATED, so build123d centers it at the origin along local Z,
    unlike `flanged_bushing`'s flange which starts at z=0). This is the wide face on the opposite side
    from the boss — the one that seats flush against whatever the hub mounts to (a shaft shoulder,
    another hub, etc). Outward normal points -Z (away from the part)."""
    from packages.subsystems.base import Frame
    return Frame(origin=(0.0, 0.0, -p.disc_thickness_mm / 2.0), normal=(0.0, 0.0, -1.0))


def _boss_tip(p):
    """Local mate frame at the raised boss's far tip — z = disc_thickness_mm/2 + boss_height_mm by
    construction (the boss is `Pos(0,0, disc_thickness/2 + boss_height/2) * Cylinder(...)`, i.e. stacked
    directly on top of the disc's own +Z face). Outward normal is +Z — where a gear/pulley/wheel hub
    bore would seat over the boss."""
    from packages.subsystems.base import Frame
    z = p.disc_thickness_mm / 2.0 + p.boss_height_mm
    return Frame(origin=(0.0, 0.0, z), normal=(0.0, 0.0, 1.0))


HUB = register_subsystem(Subsystem(
    name="hub",
    description="Stepped hub — disc + boss + through-bore (gear/pulley mounting)",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing"),
    params=[
        ParamSpec("disc_dia_mm",       value=40.0, min=10.0, max=200.0, unit="mm"),
        ParamSpec("disc_thickness_mm", value=5.0,  min=1.5,  max=25.0,  unit="mm"),
        ParamSpec("boss_dia_mm",       value=20.0, min=6.0,  max=100.0, unit="mm"),
        ParamSpec("boss_height_mm",    value=12.0, min=3.0,  max=60.0,  unit="mm"),
        ParamSpec("bore_dia_mm",       value=8.0,  min=2.0,  max=80.0,  unit="mm"),
    ],
    build=_build, volume=_volume, invariants=_check,
    # 2026-07-28 (interface-coverage sweep, final wave): a stepped two-diameter shape — wide disc
    # (z=-disc_thickness/2..+disc_thickness/2, CENTERED at the origin, unlike `flanged_bushing`'s
    # flange which starts at z=0) with a narrower boss stacked on top of the disc's +Z face
    # (z=+disc_thickness/2..+disc_thickness/2+boss_height) — neither `cylinder_end_interfaces` (assumes
    # a single-diameter cylinder) nor `plate_face_interfaces` fits, so bespoke frames computed from the
    # part's own real z-offsets instead (same shape family as `flanged_bushing`/`T_nut`, different
    # origin convention). `disc_face` is the wide mounting face opposite the boss; `boss_tip` is the
    # boss's free end (where a gear/pulley/wheel would seat).
    interfaces=[
        InterfaceSpec(name="disc_face", kind="mount", frame=_disc_face),
        InterfaceSpec(name="boss_tip", kind="mount", frame=_boss_tip),
    ],
))

"""Z-bracket — three flanges in a Z shape (two horizontal legs offset by a vertical connector)."""

from __future__ import annotations

from packages.subsystems import InterfaceSpec, ParamSpec, Subsystem, register_subsystem

_FRAGMENT = """\
## Subsystem: Z-bracket
Three flanges in a Z pattern — mounts one plane offset above another (offset shelf brackets).
- **top_length_mm × top_width_mm** — upper flange (typically the mounting face).
- **connector_height_mm** — the vertical offset between the two horizontal faces.
- **bottom_length_mm × bottom_width_mm** — lower flange.
- **thickness_mm** — same across all three legs.\
"""

_MIN_WALL_MM = 0.8


def _build(p):
    import build123d as bd
    from packages.truth_plane.regen.templated import TaggedPart
    t = p.thickness_mm
    top = bd.Pos(-p.top_length_mm / 2.0, 0.0, p.connector_height_mm + t / 2.0) \
          * bd.Box(p.top_length_mm, p.top_width_mm, t)
    conn = bd.Pos(-t / 2.0, 0.0, p.connector_height_mm / 2.0) \
           * bd.Box(t, p.top_width_mm, p.connector_height_mm)
    bot = bd.Pos(p.bottom_length_mm / 2.0, 0.0, t / 2.0) \
          * bd.Box(p.bottom_length_mm, p.bottom_width_mm, t)
    return TaggedPart(top + conn + bot, {
        "top.flange": {"kind": "solid"},
        "connector.body": {"kind": "solid"},
        "bottom.flange": {"kind": "solid"},
    })


def _volume(p):
    t = p.thickness_mm
    return (p.top_length_mm * p.top_width_mm * t
            + t * max(p.top_width_mm, p.bottom_width_mm) * p.connector_height_mm
            + p.bottom_length_mm * p.bottom_width_mm * t)


def _check(p):
    if p.thickness_mm < _MIN_WALL_MM:
        return [f"thickness {p.thickness_mm:.2f} mm < min wall {_MIN_WALL_MM} mm"]
    return []


def _top_face(p):
    """Local mate frame at the top flange's outer top face -- by construction (`_build`) the top
    flange is `bd.Pos(-top_length_mm/2, 0, connector_height_mm + t/2) * Box(top_length_mm,
    top_width_mm, t)`, i.e. NOT centered at the origin: its x-span is [-top_length_mm, 0] (center
    -top_length_mm/2) and its z-span is [connector_height_mm, connector_height_mm + t]. The face at
    z = connector_height_mm + t is the flange's free outer face -- typically the mounting face
    (per the fragment) -- with nothing else in the union above it. Outward normal is +Z."""
    from packages.subsystems.base import Frame
    return Frame(origin=(-p.top_length_mm / 2.0, 0.0, p.connector_height_mm + p.thickness_mm),
                 normal=(0.0, 0.0, 1.0))


def _bottom_face(p):
    """Local mate frame at the bottom flange's outer bottom face -- by construction the bottom
    flange is `bd.Pos(bottom_length_mm/2, 0, t/2) * Box(bottom_length_mm, bottom_width_mm, t)`, i.e.
    its x-span is [0, bottom_length_mm] (center bottom_length_mm/2) and its z-span is [0, t] -- z=0
    is the flange's free outer face, nothing else in the union below it. Outward normal is -Z."""
    from packages.subsystems.base import Frame
    return Frame(origin=(p.bottom_length_mm / 2.0, 0.0, 0.0), normal=(0.0, 0.0, -1.0))


Z_BRACKET = register_subsystem(Subsystem(
    name="z_bracket",
    description="Three-flange Z bracket — offset shelf mount",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing", "thermal"),
    params=[
        ParamSpec("top_length_mm",       value=40.0, min=10.0, max=200.0, unit="mm"),
        ParamSpec("top_width_mm",        value=30.0, min=10.0, max=200.0, unit="mm"),
        ParamSpec("connector_height_mm", value=30.0, min=5.0,  max=200.0, unit="mm"),
        ParamSpec("bottom_length_mm",    value=40.0, min=10.0, max=200.0, unit="mm"),
        ParamSpec("bottom_width_mm",     value=30.0, min=10.0, max=200.0, unit="mm"),
        ParamSpec("thickness_mm",        value=3.0,  min=0.8,  max=15.0,  unit="mm"),
    ],
    build=_build, volume=_volume, invariants=_check,
    # 2026-07-28 (interface-coverage sweep, final wave): three fused boxes forming a Z -- neither
    # `plate_face_interfaces` nor `box_face_interfaces` fits (two DIFFERENT-sized flanges, each offset
    # off-center, not one box centered at the origin) -- bespoke frames computed from the two flanges'
    # real, un-centered z/x offsets instead, same pattern as `stepped_spacer`'s bottom_face/top_face.
    # `top_face` is the top flange's outer face (typically the mounting face per the fragment);
    # `bottom_face` is the lower flange's outer face -- the bracket's two real mount points.
    interfaces=[
        InterfaceSpec(name="top_face", kind="mount", frame=_top_face),
        InterfaceSpec(name="bottom_face", kind="mount", frame=_bottom_face),
    ],
))

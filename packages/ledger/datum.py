"""Coordinate frames & datums — the shared reference everything is expressed in.

Closes the "no datum management" gap: multi-section reassembly, alignment-pin registration, and
CG%MAC all require ONE body frame and (for aero) a defined MAC reference. Translation-only placement
is enough for the wedge (assembling printed sections into a common frame); rotation can extend it.
"""

from __future__ import annotations

from dataclasses import dataclass

Point = tuple[float, float, float]


@dataclass(frozen=True)
class BodyFrame:
    """The single frame all masses and geometry are expressed in (x aft, z up by convention)."""
    origin_mm: Point = (0.0, 0.0, 0.0)


@dataclass(frozen=True)
class Placement:
    """A part's placement in the body frame (translation only, for now)."""
    translation_mm: Point = (0.0, 0.0, 0.0)

    def to_body(self, local_point: Point) -> Point:
        return tuple(local_point[i] + self.translation_mm[i] for i in range(3))


@dataclass(frozen=True)
class MacReference:
    """Mean Aerodynamic Chord reference for CG%MAC (aerospace tier; unused by the parts wedge)."""
    leading_edge_x_mm: float
    mac_length_mm: float

    def percent_mac(self, cg_x_mm: float) -> float:
        if self.mac_length_mm <= 0:
            raise ValueError("mac_length must be > 0")
        return (cg_x_mm - self.leading_edge_x_mm) / self.mac_length_mm * 100.0

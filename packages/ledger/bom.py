"""Material database + positioned Bill-of-Materials -> computable mass & CG.

Closes two gaps: `material_profile`/`cell_type` were bare strings (no density -> mass uncomputable;
no E/nu/yield -> FEA can't run), and there was no positioned non-structural mass (batteries, motors,
fasteners dominate CG but were absent). Masses are expressed in ONE body datum frame (see datum.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True)
class Material:
    name: str
    density_g_per_mm3: float
    youngs_mod_mpa: float
    poisson: float
    yield_mpa: float
    service_temp_c: float = 50.0  # max continuous-use temp (thermal discipline L0 gate)
    cost_per_kg_usd: float = 25.0  # 2026 dev-default; overridden per material in MATERIAL_DB


# Minimal, queryable allowables DB (replaces bare string keys). Values are representative.
# service_temp_c ≈ practical continuous-use limit (thermoplastics near glass transition; metals well below).
# cost_per_kg_usd ≈ representative 2026 stock prices; real project pricing → cost discipline knowledge fragment.
MATERIAL_DB: dict[str, Material] = {
    "PLA":     Material("PLA",     1.24e-3,   3500.0, 0.36,  50.0,  55.0,  22.0),
    "PETG":    Material("PETG",    1.27e-3,   2100.0, 0.40,  50.0,  70.0,  25.0),
    "ABS":     Material("ABS",     1.04e-3,   2200.0, 0.35,  40.0,  90.0,  23.0),
    "AL6061":  Material("AL6061",  2.70e-3,  68900.0, 0.33, 276.0, 200.0,   8.0),  # raw stock; machining is extra
    "STEEL":   Material("STEEL",   7.85e-3, 210000.0, 0.30, 250.0, 400.0,   2.0),  # raw stock
}


def material(name: str) -> Material:
    try:
        return MATERIAL_DB[name]
    except KeyError as e:
        raise KeyError(f"unknown material '{name}' (known: {sorted(MATERIAL_DB)})") from e


class ComponentKind(str, Enum):
    STRUCTURAL = "STRUCTURAL"   # printed structure
    PAYLOAD = "PAYLOAD"
    POWER = "POWER"             # batteries
    HARDWARE = "HARDWARE"       # motors, fasteners, inserts


@dataclass(frozen=True)
class Component:
    name: str
    mass_g: float
    centroid_mm: tuple[float, float, float]   # in the body datum frame
    kind: ComponentKind = ComponentKind.HARDWARE


@dataclass
class BOM:
    components: list[Component]

    def total_mass_g(self) -> float:
        return sum(c.mass_g for c in self.components)

    def cg_mm(self) -> tuple[float, float, float]:
        m = self.total_mass_g()
        if m <= 0:
            raise ValueError("total mass must be > 0 to compute CG")
        return tuple(sum(c.mass_g * c.centroid_mm[i] for c in self.components) / m for i in range(3))

    def mass_breakdown_g(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for c in self.components:
            out[c.kind.value] = out.get(c.kind.value, 0.0) + c.mass_g
        return out

    def printed_mass_g(self, material_name: str, volume_mm3: float) -> float:
        """Mass of printed structure from material density × volume (the missing density link)."""
        return material(material_name).density_g_per_mm3 * volume_mm3

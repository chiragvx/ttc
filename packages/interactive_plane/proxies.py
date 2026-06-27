"""Interactive Plane — closed-form analytic proxies for the 30 Hz HUD.

CONTRACT (see packages/interactive_plane/CLAUDE.md): NO OCCT, NO LLM, NO solver, NO I/O. Pure
arithmetic only, target <1 ms per number. These feed the floor-rail HUD during a slider drag; the
real B-rep regen + true mass integration happen later in the Truth Plane, debounced to release.

Spike 5 measures how far these proxies may diverge from the real regen before the HUD must show
"unknown" (kill threshold: >2-3% on mass/CG).
"""

from __future__ import annotations

from collections.abc import Mapping


def total_mass_g(component_volumes_mm3: Mapping[str, float],
                 densities_g_per_mm3: Mapping[str, float]) -> float:
    """mass = Σ ρ_i · V_i over the positioned BOM. Densities come from the (versioned) material DB."""
    return sum(component_volumes_mm3[k] * densities_g_per_mm3[k] for k in component_volumes_mm3)


def center_of_gravity_mm(masses_g: Mapping[str, float],
                         centroids_mm: Mapping[str, tuple[float, float, float]]) -> tuple[float, float, float]:
    """CG = Σ(m_i · r_i) / Σ m_i, in one declared body datum frame. Requires a positioned BOM —
    the masses that dominate CG (batteries/motors/etc.) must exist in the ledger, not just printed volume."""
    total = sum(masses_g.values())
    if total <= 0:
        raise ValueError("total mass must be > 0 to compute CG")
    cx = sum(masses_g[k] * centroids_mm[k][0] for k in masses_g) / total
    cy = sum(masses_g[k] * centroids_mm[k][1] for k in masses_g) / total
    cz = sum(masses_g[k] * centroids_mm[k][2] for k in masses_g) / total
    return (cx, cy, cz)


def print_time_seconds(extrusion_volume_mm3: float, flow_rate_mm3_per_s: float) -> float:
    """Analytic estimate = extruded volume / flow rate. The HONEST headline number comes from a real
    slicer run (Truth Plane), debounced to Generate-G-Code and cached by mesh hash; this is the
    live, labeled-as-estimate proxy only."""
    if flow_rate_mm3_per_s <= 0:
        raise ValueError("flow_rate must be > 0")
    return extrusion_volume_mm3 / flow_rate_mm3_per_s

"""Analytic print-time / material estimator + supportless-overhang check.

This is the *labeled estimate* (the live HUD proxy). The authoritative print time/material comes from
a real slicer run, debounced to Generate-G-Code and cached by mesh hash — deferred here because every
production FDM slicer is AGPL-3.0 and must run as a network-isolated out-of-process sidecar (the
architecture-blocking decision). No kernel needed; takes volume + an overhang angle as inputs.
"""

from __future__ import annotations

from dataclasses import dataclass

from packages.ledger.bom import material

# default supportless overhang ceiling (PRD: 45-50 deg)
OVERHANG_LIMIT_DEG = 50.0


@dataclass
class PrintEstimate:
    print_time_s: float
    material_g: float
    material_volume_mm3: float
    is_estimate: bool = True  # always — the real number comes from the slicer sidecar


def estimate_print(
    volume_mm3: float,
    material_name: str,
    *,
    infill_frac: float = 0.2,
    wall_fraction: float = 0.25,
    volumetric_flow_mm3_s: float = 5.0,
) -> PrintEstimate:
    """Crude but honest: material volume = walls (solid) + infill of the remainder; time = vol / flow.
    Labeled an ESTIMATE — never used as the export-gate number."""
    solid_frac = wall_fraction + (1.0 - wall_fraction) * infill_frac
    mat_vol = volume_mm3 * solid_frac
    grams = material(material_name).density_g_per_mm3 * mat_vol
    return PrintEstimate(
        print_time_s=mat_vol / max(1e-9, volumetric_flow_mm3_s),
        material_g=grams,
        material_volume_mm3=mat_vol,
    )


def overhang_supportless_ok(max_overhang_deg: float, limit_deg: float = OVERHANG_LIMIT_DEG) -> bool:
    """True if the steepest overhang is within the supportless ceiling (measured from vertical)."""
    return max_overhang_deg <= limit_deg

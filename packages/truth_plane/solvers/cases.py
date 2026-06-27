"""Reference load cases with CLOSED-FORM solutions — the honest oracle for FEA validation.

The golden value is the analytical formula (Euler-Bernoulli beam theory), never an FEA run. A solver
that can't reproduce these to a few percent is wrong, full stop.
"""

from __future__ import annotations

from dataclasses import dataclass

import build123d as bd


@dataclass(frozen=True)
class Cantilever:
    """End-loaded cantilever: beam along +x (length L), cross-section width w (y) x height h (z),
    clamped at min-x, point load P (N) in -z at the free end. All lengths mm, stress MPa (N/mm^2)."""

    length_mm: float
    width_mm: float
    height_mm: float
    youngs_mod_mpa: float
    poisson: float
    yield_mpa: float
    tip_load_n: float

    def solid(self):
        # build123d Box is centred at the origin -> faces at x = -L/2 (clamp) and +L/2 (load).
        return bd.Box(self.length_mm, self.width_mm, self.height_mm).solid()

    @property
    def second_moment_mm4(self) -> float:
        # bending about the y-axis (load in z): I = w * h^3 / 12
        return self.width_mm * self.height_mm ** 3 / 12.0

    @property
    def analytical_tip_deflection_mm(self) -> float:
        # delta = P L^3 / (3 E I)  — convergent, non-singular: the validation oracle
        return (self.tip_load_n * self.length_mm ** 3) / (3.0 * self.youngs_mod_mpa * self.second_moment_mm4)

    @property
    def analytical_nominal_stress_mpa(self) -> float:
        # nominal max bending stress at the clamp extreme fibre: sigma = 6 P L / (w h^2)
        # NOTE: FEA peak stress here is singular (clamp) and will OVERSHOOT this — see findings.
        return 6.0 * self.tip_load_n * self.length_mm / (self.width_mm * self.height_mm ** 2)

    @property
    def analytical_fs(self) -> float:
        return self.yield_mpa / self.analytical_nominal_stress_mpa

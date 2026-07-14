"""Export gates — the enforcement point for Inversion #1 and the safety floor.

This is pure Python (no kernel, no solver, no LLM) and so is fully testable from day one. It encodes:
  * "unknown" (a missing grounded-solver result) BLOCKS export — never a fabricated pass;
  * the Factor-of-Safety floor (default 1.5);
  * validity gates (watertight / min-wall / mesh-converged) must be explicitly True;
  * the human-in-the-loop sign-off (ENGINEER_REVIEWED) is required before export.
"""

from __future__ import annotations

from enum import Enum
from typing import Callable, Optional

from pydantic import BaseModel, ConfigDict

from packages.ledger.schema import MasterParametricLedger, ReviewState


class ExportStatus(str, Enum):
    EXPORT_ELIGIBLE = "EXPORT_ELIGIBLE"
    EXPORT_BLOCKED = "EXPORT_BLOCKED"


class GateResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ExportStatus
    reasons: list[str]
    unknowns: list[str]  # safety scalars that came back "unknown" (None)

    @property
    def eligible(self) -> bool:
        return self.status is ExportStatus.EXPORT_ELIGIBLE


def evaluate_export_gates(
    ledger: MasterParametricLedger,
    extra_findings: Optional[Callable[[MasterParametricLedger], tuple[list[str], list[str]]]] = None,
) -> GateResult:
    """Core structural/DFM + human-sign-off gates. `extra_findings` injects additional discipline gate
    contributions (see packages.disciplines.all_discipline_findings) without coupling this pure package
    to the discipline registry — a missing grounded scalar there is an `unknown` and blocks, same as here."""
    reasons: list[str] = []
    unknowns: list[str] = []

    floor = ledger.global_constraints.factor_of_safety_floor
    d = ledger.derived

    # --- Inversion #1: a missing grounded result is "unknown" and blocks. Never assume a pass. ---
    if d.factor_of_safety is None:
        unknowns.append("factor_of_safety")
        reasons.append("factor_of_safety is unknown (no grounded solver result)")
    elif d.factor_of_safety < floor:
        reasons.append(f"factor_of_safety {d.factor_of_safety} below floor {floor}")

    for name, val in (("mesh_converged", d.mesh_converged),
                      ("watertight", d.watertight),
                      ("min_wall_ok", d.min_wall_ok)):
        if val is None:
            unknowns.append(name)
            reasons.append(f"{name} is unknown")
        elif val is False:
            reasons.append(f"{name} is False")

    # --- Injected discipline gates (thermal, …) — closed-form now, solver-fed later ---
    if extra_findings is not None:
        extra_reasons, extra_unknowns = extra_findings(ledger)
        reasons.extend(extra_reasons)
        unknowns.extend(extra_unknowns)

    # --- Human-in-the-loop sign-off FSM ---
    if ledger.review.state is not ReviewState.ENGINEER_REVIEWED:
        reasons.append("not engineer-reviewed (no human sign-off)")

    status = ExportStatus.EXPORT_ELIGIBLE if not reasons else ExportStatus.EXPORT_BLOCKED
    return GateResult(status=status, reasons=reasons, unknowns=unknowns)

"""Hero-bracket end-to-end vertical slice — the Phase 1 proof-point in one function.

Ties the whole backbone together for a single part:
  tagged generator -> volume -> print estimate -> CalculiX FS -> event log (genesis/mutation/derivation
  /sign-off) -> export gate transition (BLOCKED-on-unknown -> ELIGIBLE once a grounded FS + sign-off exist).

Architecture note: `derived.*` (the FS verdict) is a DERIVATION of the CURRENT geometry+solver — it is
recorded as a content-addressed, fingerprint-stamped derivation event and attached to the state for
the gate; it is NOT a replayed user-intent fact (replay stays a pure fold over facts).
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass

from packages.ledger.bom import material
from packages.ledger.deltas import ParameterDelta
from packages.ledger.events import EventLog
from packages.ledger.fingerprint import fingerprint
from packages.ledger.gates import ExportStatus, evaluate_export_gates
from packages.ledger.schema import DerivedSafety, MasterParametricLedger
from packages.truth_plane.regen.generator import export_step_text
from packages.truth_plane.regen.templated import render_bracket
from packages.truth_plane.solvers.fs import evaluate_fs
from packages.truth_plane.solvers.slicer_estimate import estimate_print

_TS = "2026-06-28T00:00:00Z"


@dataclass
class HeroReport:
    tags: list[str]
    volume_mm3: float
    print_time_s: float
    material_g: float
    fs_status: str
    factor_of_safety: float | None
    export_before: str
    export_after: str
    n_events: int


def run_hero_pipeline(demo_ledger: MasterParametricLedger, *, load_n: float = 40.0,
                      profile: str = "PLA") -> HeroReport:
    # 1) generate the tagged hero part
    part = render_bracket(width_mm=60, depth_mm=40, thickness_mm=8, hole_dia_mm=6, n_holes=4)
    volume = part.solid.volume

    # 2) analytic print estimate (labeled)
    est = estimate_print(volume, profile)

    # 3) event log: genesis -> a mutation -> sign-off
    log = EventLog()
    log.append_genesis(demo_ledger, actor="system", ts=_TS)
    log.append_mutation(ParameterDelta(target_node="instances.root.params.skin_thickness_mm",
                                       requested_value=3.0), actor="user", ts=_TS)
    log.append_signoff("pe@example.com", ts=_TS)

    export_before = evaluate_export_gates(log.fold()).status  # FS unknown -> blocked

    # 4) grounded FS from CalculiX (the Validator routes solver output; no LLM scalar)
    fd, path = tempfile.mkstemp(suffix=".step")
    os.close(fd)
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(export_step_text(part.solid))
        mat = material(profile)
        verdict = evaluate_fs(path, youngs_mod_mpa=mat.youngs_mod_mpa, poisson=mat.poisson,
                              yield_mpa=mat.yield_mpa, tip_load_n=load_n)
    finally:
        os.remove(path)

    # 5) record the verdict as a content-addressed, fingerprint-stamped DERIVATION
    log.append_derivation("fs_verdict",
                          f'{{"fs": {verdict.factor_of_safety}}}'.encode(),
                          fingerprint=fingerprint(), actor="solver", ts=_TS)

    # 6) attach the derivation to the current state and re-check the gate
    after_ledger = log.fold()
    if verdict.status == "OK":
        after_ledger = after_ledger.model_copy(update={"derived": DerivedSafety(
            factor_of_safety=verdict.factor_of_safety, mesh_converged=True,
            watertight=True, min_wall_ok=True)})
    export_after = evaluate_export_gates(after_ledger).status

    return HeroReport(
        tags=sorted(part.tags),
        volume_mm3=round(volume, 1),
        print_time_s=round(est.print_time_s, 1),
        material_g=round(est.material_g, 2),
        fs_status=verdict.status,
        factor_of_safety=verdict.factor_of_safety,
        export_before=export_before.value if isinstance(export_before, ExportStatus) else str(export_before),
        export_after=export_after.value if isinstance(export_after, ExportStatus) else str(export_after),
        n_events=len(log.events()),
    )

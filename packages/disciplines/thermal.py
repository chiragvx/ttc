"""Thermal discipline — the proof-of-pattern third lens (DOMAIN_TAXONOMY.md §3.9).

Two grounded tiers, both honest:
  * L0 (now): a closed-form material service-temperature check. operating_temp > material service temp
    ⇒ a real, deterministic export block ("upgrade the material"). No solver, no guessing.
  * L1 (later): a positive heat load (power_dissipation_w > 0) needs a real CalculiX steady-state
    heat-transfer verdict for the part's peak temperature. Until that solver is wired, the thermal
    margin is `unknown` ⇒ export blocked (Inversion #1 — never a fabricated green light).

Active only when a thermal domain is present on the ledger (opt-in; existing brackets are unaffected).

2026-07-15 — the service-temp ladder in the knowledge fragment, and the gate's "upgrade material"
suggestion, both now read live packages.ledger.bom.MATERIAL_DB (the same dict
packages/catalog/bootstrap.py::set_material_db() overrides at process startup) instead of a frozen
"PLA ~55 °C < PETG ~70 °C < ..." string, so neither can cite a material/temperature the catalog no
longer has loaded. The knowledge fragment is a CALLABLE now, resolved at PROMPT-BUILD time (see
packages/disciplines/__init__.py::_fragment_text) — same pattern manufacturing.py established for its
clearance-hole quick-ref.
"""

from __future__ import annotations

from packages.disciplines import register
from packages.disciplines.base import DisciplineSpec, GateFinding
from packages.ledger.bom import material
from packages.ledger.nodes import OPERATING_TEMP, POWER_DISSIPATION
from packages.ledger.schema import MasterParametricLedger


def _service_temp_ladder() -> str:
    from packages.ledger.bom import MATERIAL_DB

    ordered = sorted(MATERIAL_DB.values(), key=lambda m: m.service_temp_c)
    return " < ".join(f"{m.name} ~{m.service_temp_c:.0f} °C" for m in ordered)


def _fragment() -> str:
    return f"""\
## Discipline: Thermal (service-temp & heat dissipation)
Governs whether the part survives its thermal environment — often the binding constraint for a printed
thermoplastic. You never state a temperature margin; it is a lookup (L0) or a CalculiX heat verdict (L1).
- **operating_temp_c** — the environment/service temperature the part must survive. If it exceeds the
  chosen material's service temp, the design is BLOCKED — recommend a higher-temp material:
  {_service_temp_ladder()}.
- **power_dissipation_w** — heat load from mounted electronics (motor/ESC/board). 0 = passive part.
  A positive load requires a grounded thermal-FEA margin before export; until then it reads as unknown.
- Guidance: "runs hot" / "near a motor" ⇒ raise operating_temp_c and/or set power_dissipation_w; propose
  the next material up the ladder above if the current one can't take it."""


def _is_active(ledger: MasterParametricLedger) -> bool:
    return ledger.domains.thermal is not None


def _upgrade_candidates(current: str, op: float) -> str:
    from packages.ledger.bom import MATERIAL_DB

    ordered = sorted(
        (m for m in MATERIAL_DB.values() if m.name != current and m.service_temp_c >= op),
        key=lambda m: m.service_temp_c,
    )
    names = [m.name for m in ordered]
    return "/".join(names) if names else "a higher-temp material"


def _gate(ledger: MasterParametricLedger) -> GateFinding:
    t = ledger.domains.thermal
    if t is None:
        return GateFinding()
    reasons: list[str] = []
    unknowns: list[str] = []

    mat = material(ledger.domains.structure.material_profile)
    op = t.operating_temp_c.value
    # L0 — closed-form material service-temp limit (a real, deterministic gate today)
    if op > mat.service_temp_c:
        reasons.append(
            f"operating temp {op:.0f}°C exceeds {mat.name} service temp {mat.service_temp_c:.0f}°C "
            f"— upgrade material ({_upgrade_candidates(mat.name, op)})"
        )
    # L1 — an active heat load needs a grounded thermal-FEA margin (solver not yet wired) -> unknown
    if t.power_dissipation_w.value > 0:
        unknowns.append("thermal_margin_c")
        reasons.append(
            f"thermal margin unknown for {t.power_dissipation_w.value:.0f} W heat load "
            f"(needs CalculiX heat-transfer solver — not yet wired)"
        )
    return GateFinding(reasons=reasons, unknowns=unknowns)


THERMAL = register(DisciplineSpec(
    name="thermal",
    description="Service-temp limits (L0 closed-form) + heat-dissipation margin (L1 CalculiX, later)",
    knowledge_fragment=_fragment,  # callable — see this module's docstring
    owned_params=(OPERATING_TEMP, POWER_DISSIPATION),
    geometry_params=(),  # thermal inputs are loads/requirements — they do not change the geometry
    is_active=_is_active,
    evaluate_gate=_gate,
))

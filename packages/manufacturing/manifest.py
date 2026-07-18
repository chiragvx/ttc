"""Manufacturability outputs (Phase 6) — a human-readable assembly-step list plus a per-part
make-manifest (material + CNC-vs-print process). Codifies the SAME rule already taught to the LLM in
prose (packages/disciplines/manufacturing.py's knowledge fragment: "Rules for FDM/FFF unless the
material is metal (then CNC)") as a structured lookup — this module does not invent new manufacturing
judgment, it makes an existing one computable.

Pure module — no OCCT/LLM/solver/I-O, mirroring packages/couplings/resolve.py's purity boundary:
frozen dataclasses, a TYPE_CHECKING-only ledger import, pure functions taking the ledger as a plain
parameter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from packages.ledger.schema import MasterParametricLedger

# The metals in the material DB (packages/ledger/bom.py::MATERIAL_DB) — everything else is a
# thermoplastic, hence FDM/print. Matches packages/disciplines/manufacturing.py's prose 1:1.
_CNC_MATERIALS = frozenset({"AL6061", "STEEL"})


@dataclass(frozen=True)
class PartManifestEntry:
    instance_id: str
    subsystem_type: str
    material: str
    process: str  # "CNC" | "print"


@dataclass(frozen=True)
class MakeManifest:
    material: str              # ledger-wide (Domains.structure.material_profile) — the CURRENT ledger
                                # model has ONE material for the whole design, not per-instance.
    parts: list[PartManifestEntry]
    assembly_steps: list[str]  # human-readable, one per ledger.connections entry


def _process_for(material_name: str) -> str:
    return "CNC" if material_name in _CNC_MATERIALS else "print"


_VERB_FOR_KIND = {
    "bolted": "bolt",
    "slip_fit": "slip-fit",
    "containment": "place",
    "mate": "mate",
}


def build_manifest(ledger: "MasterParametricLedger") -> "MakeManifest":
    # Imported inside the function body (not at module top) to keep this module importable with zero
    # side effects at import time — matching packages/couplings/resolve.py's style.
    from packages.ledger.bom import material as material_lookup

    material_name = ledger.domains.structure.material_profile
    mat = material_lookup(material_name)
    process = _process_for(mat.name)

    parts = [
        PartManifestEntry(
            instance_id=instance_id,
            subsystem_type=inst.subsystem_type,
            material=mat.name,
            process=process,
        )
        for instance_id, inst in sorted(ledger.instances.items())
    ]

    assembly_steps: list[str] = []
    for c in ledger.connections:
        verb = _VERB_FOR_KIND.get(c.kind, "mate")
        line = f"{verb} {c.a.instance_id}.{c.a.interface} <-> {c.b.instance_id}.{c.b.interface}"
        # round BEFORE the inclusion check (not just the display) — otherwise a sub-0.05mm gap (a real
        # value the manufacturing discipline's own clearance guidance goes as fine as, e.g. "0.1 mm
        # press-fit") displays as the contradictory "(gap 0.0mm)" instead of being omitted like a true
        # zero gap (2026-07-19 review).
        if round(c.gap_mm, 1) != 0.0:
            line += f" (gap {c.gap_mm:.1f}mm)"
        assembly_steps.append(line)

    return MakeManifest(material=mat.name, parts=parts, assembly_steps=assembly_steps)

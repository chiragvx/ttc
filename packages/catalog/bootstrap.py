"""apply_to_live_app() — the ONE function that wires packages.catalog into the running app.

Called from BOTH packages/transport/app.py::create_app() AND packages/truth_plane/worker.py (module
level) — required in both, not just the API process: packages/disciplines/{cost,thermal}.py's
material() calls also execute inside the separate Dramatiq worker process, which never touches
create_app(). The manufacturing DFM fragment override, by contrast, only matters in the API process
(it feeds LLM prompt building, which the worker never does) — calling it from both anyway is
harmless and keeps this function's contract uniform ("call me from every process, I'll apply
whatever's actually relevant there"). Each override is wrapped independently so a catalog failure
never blocks app startup or masks the OTHER overrides — reference data must never be able to crash
the app; on any error the existing hardcoded defaults simply stand.

Converts catalog's Pydantic MaterialRecord into packages.ledger.bom's Material dataclass here (not
inside packages/catalog itself) — keeps packages/catalog agnostic of its consumers' internal types.
"""

from __future__ import annotations


def apply_to_live_app() -> None:
    _apply_materials()
    _apply_machine_rate()
    _apply_manufacturing_dfm()


def _apply_materials() -> None:
    try:
        from packages.catalog.loader import get_store
        from packages.ledger.bom import Material, set_material_db

        records = get_store().materials()
        if not records:
            return
        materials = {
            name: Material(
                name=r.name, density_g_per_mm3=r.density_g_per_mm3, youngs_mod_mpa=r.youngs_mod_mpa,
                poisson=r.poisson, yield_mpa=r.yield_mpa, service_temp_c=r.service_temp_c,
                cost_per_kg_usd=r.cost_per_kg_usd,
            )
            for name, r in records.items()
        }
        set_material_db(materials)
    except Exception:
        pass  # keep the hardcoded MATERIAL_DB default — reference data must never crash the app


def _apply_machine_rate() -> None:
    try:
        from packages.catalog.loader import get_store
        from packages.disciplines.cost import set_machine_rate

        dataset = get_store().dataset("cost.machine_rates_usd_per_hr")
        if dataset is None:
            return
        entry = next((e for e in dataset.entries if e.entry_key == "fdm_default"), None)
        if entry is None or entry.value_numeric is None:
            return
        set_machine_rate(entry.value_numeric)
    except Exception:
        pass  # keep the hardcoded MACHINE_RATE_USD_PER_HR default


def _apply_manufacturing_dfm() -> None:
    """Overrides the manufacturing DFM fragment's clearance-hole quick-ref + advisory recommended
    wall thickness — NOT the hard min-wall floor, which packages/disciplines/manufacturing.py reads
    directly from packages.ledger.apply.MIN_WALL_MM (the actually-enforced constant) so the prompt
    can never claim a floor that doesn't match real export-gate enforcement."""
    try:
        from packages.catalog.loader import get_store
        from packages.disciplines.manufacturing import set_dfm_reference

        store = get_store()

        clearance_ds = store.dataset("manufacturing.clearance_holes_mm")
        clearance_holes = {
            e.entry_key: e.value_numeric for e in (clearance_ds.entries if clearance_ds else [])
            if e.value_numeric is not None
        }

        wall_ds = store.dataset("manufacturing.wall_thickness_mm")
        recommended = None
        if wall_ds is not None:
            entry = next((e for e in wall_ds.entries if e.entry_key == "recommended_wall_load_bearing"), None)
            recommended = entry.value_numeric if entry is not None else None

        set_dfm_reference(clearance_holes_mm=clearance_holes, recommended_wall_mm=recommended)
    except Exception:
        pass  # keep the hardcoded clearance-hole table / recommended-wall default

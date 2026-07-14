# Instance-Graph Refactor — Phase G

**Landed:** 2026-07-02 · Follows `SCALABLE_SUBSYSTEM_REFACTOR.md`.
**Prompt:** *"lets keep phase g first, i am afraid this might get locked in and we all forget it..."*

This document records the second major structural change in a week: from **one active subsystem +
one flat geometry bag** to **an instance tree** where any project holds N named subsystem instances.
It supersedes the flat `domains.geometry: dict[str, ParameterDef]` shape.

## Why we changed it

The prior scalable-subsystem refactor solved *adding a part type* (each subsystem = one file). But
the ledger still assumed **one active subsystem at a time**:

- `ProjectMetadata.subsystem_type: str = "bracket"`
- `Domains.geometry: dict[str, ParameterDef]` — that one subsystem's params

That model handles single-part designs (all wedge parts) and even multi-body compounds (like
`enclosure` = box + lid, `table` = top + legs). But it doesn't handle **hierarchical designs where
each sub-part has its own editable identity** — a UAV, a robot, a machine assembly. In those
domains the user needs to click "wing_left" and edit its span independently of "wing_right".

Every new part written against the flat model reinforced its assumptions in tests, prompt builder,
adapters. The user flagged this correctly: **once catalog growth locks in that shape, retrofitting
becomes very hard.** Do the ledger-shape work now while there are 23 parts, not at 100+.

## The new shape

```
MasterParametricLedger
├─ project_metadata            — no more subsystem_type here
├─ global_constraints
├─ domains                     — cross-cutting DISCIPLINES only (Domains.geometry REMOVED)
│   ├─ structure               — material_profile (typed discipline)
│   ├─ manufacturing           — build_orientation, slip_fit (typed discipline)
│   └─ thermal   (Optional)    — operating_temp, power_dissipation
├─ instances                   — the design tree (Phase G)
│   └─ dict[str, Instance]     — keyed by unique id
├─ root_id: str                — points to the root instance
├─ derived                     — solver outputs
└─ review

Instance
├─ id: str                     — unique within the project
├─ subsystem_type: str         — key into SUBSYSTEM_REGISTRY
├─ params: dict[str, ParameterDef]  — this instance's params (indexed by ParamSpec.name)
├─ transform: Optional[Transform]   — position + rotation relative to parent (identity if None)
└─ parent_id: Optional[str]    — None == root
```

For a **single-part design** (every wedge part today):
- `instances = {"root": Instance(id="root", subsystem_type="bracket", params={...}, parent_id=None)}`
- `root_id = "root"`

For a **hierarchical design** (future UAV, robot):
- `instances = {"uav": Instance(...), "fuselage": Instance(parent_id="uav", ...),
                 "wing_left": Instance(parent_id="uav", ...), ...}`
- `root_id = "uav"`

## Path convention

- Discipline attributes (unchanged): `domains.structure.material_profile`, `domains.manufacturing.build_orientation_deg`, etc.
- Instance params (NEW): `instances.<id>.params.<name>` — e.g. `instances.root.params.skin_thickness_mm`.
- No more `domains.geometry.<name>`.

The delta emitter, WS mutations, tests, prompt builder all use the instance-path convention.

## Multi-instance features (deferred)

Deliberately NOT built in Phase G:
- Multi-instance UI (an outliner panel that lists instances and lets you pick one). Adds it when a hierarchical design (UAV, robot) exists.
- Multi-instance prompt affordances (`add_instance`, `remove_instance`, `edit_instance` copilot actions). Adds them when needed.
- Cross-subsystem composition helpers (`call(name, **overrides)`, `place`, `place_polar`, tag namespacing). These are Phase F, still deferred.
- Positioning helpers (`transform` currently exists on `Instance` but no code positions bodies yet).

Every wedge part is a single-instance design in the tree today. The tree data shape is in place so
these features can land later WITHOUT another core refactor.

## Migration (5 phases, tests green at every stop)

- **G1** — Added `Instance`, `Transform` schema types; `instances: dict` + `root_id: str` on `MasterParametricLedger`; `_resolve` handles instance-tree paths; `iter_parameters` descends into instances. Compat shim added mapping `domains.geometry.<name>` ↔ `instances.<root_id>.params.<name>`.
- **G2** — `Subsystem.seed_defaults` populates `instances[root]` (also mirrored to `Domains.geometry` during transition). `resolve_namespace` reads from the root instance. `apply_delta` calls a post-mutation mirror sync.
- **G3** — `SessionState.current_params` and `/optimize` bounds lookup read from the instance tree as source of truth.
- **G4** — Batch-renamed `domains.geometry.<name>` → `instances.root.params.<name>` across:
  - dotted-path strings (constants + delta target nodes)
  - JSON accessors in tests (`d["domains"]["geometry"][...]` → `d["instances"]["root"]["params"][...]`)
  - Python attribute writes (`led.domains.geometry["…"] = …` → `led.instances["root"].params["…"] = …`)
  - `packages/frontend/src/types.ts` path constants (SKIN, RIB, WIDTH, DEPTH, HOLE_DIA)
  - `packages/ledger/nodes.py`, `derived_resolver.py::GEOMETRY_PARAMS`
- **G5** — Removed `Domains.geometry` field, the compat shim in `_resolve`, `_sync_geometry_mirror`, and all remaining direct references. `check_invariants` reads the ROOT instance's params (not the stale mirror). Base test fixtures and helpers rewritten to populate `instances["root"]` only.

## Verified

- **225 backend tests + frontend typecheck** green at every phase boundary.
- Live app: `/subsystems`, `/params`, `/mesh`, `/export/step`, `/project/subsystem`, WS mutations, chat, cost telemetry all continue to work — because the app.py and prompt builder now read from `instances[root_id]` uniformly.

## Files touched

- **`packages/ledger/schema.py`** — added `Instance` + `Transform`; removed `Domains.geometry`.
- **`packages/ledger/apply.py`** — `_resolve` walks instance-tree paths uniformly; `check_invariants` reads the root instance's params. Compat shim REMOVED.
- **`packages/ledger/branch.py`** — `iter_parameters` descends into `instances` dict.
- **`packages/ledger/nodes.py`, `derived_resolver.py`, `deltas.py`, `truth_plane/demo_pipeline.py`** — path constants and docstrings updated.
- **`packages/subsystems/base.py`** — `seed_ledger_geometry` seeds the root instance (no mirror).
- **`packages/subsystems/__init__.py`** — `SubsystemContext` adapter emits `instances.root.params.<name>` in `geometry_params`.
- **`packages/transport/app.py`** — `current_params` and `/optimize` read from the root instance.
- **`packages/frontend/src/types.ts`** — SKIN/RIB/WIDTH/DEPTH/HOLE_DIA constants updated.
- **`tests/conftest.py`, `tests/subsystems/conftest.py`, `tests/acceptance/test_export_gates.py`** — base fixtures populate `instances["root"]` directly, no legacy mirror.
- Batch path renames across ~15 test files.

## Anti-lock-in payoff

- The instance model is in the schema NOW. Any hierarchical design (UAV, robot, machine assembly) can be added as a multi-instance tree without another core refactor.
- The single-part designs the catalog is full of are trivially one-instance trees.
- Adding a new subsystem is still one file (per `SCALABLE_SUBSYSTEM_REFACTOR.md`).
- When the user says "make me a UAV" and the copilot needs to instantiate wing + fuselage + empennage etc., the schema already supports it — the only remaining work is the multi-instance prompt affordances and UI, which can land per-need.

## What's next (from the roadmap)

1. Continue curating `SUBSYSTEM_PROPOSALS.md` and add wedge parts.
2. When the first hierarchical design lands (e.g. a real UAV or robot with explicit go), build the multi-instance UI (outliner) and prompt affordances (add_instance, edit_instance, remove_instance) on top of this schema.
3. Phase F composition helpers (`call`, `place`, `place_polar`) — still deferred until a composite-of-registered-parts subsystem actually needs them.

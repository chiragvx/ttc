# Scalable Subsystem Architecture — Refactor Record

**Landed:** 2026-07-02 · **Plan:** `C:\Users\Chirag\.claude\plans\cosmic-herding-toucan.md`
**Prompt:** *"I am afraid that when we reach a thousand subsystems then you're gonna have a heart attack."*

This document records a major schema/architecture change to the codebase. It supersedes the shape
described in `prd-27-8.14/prd4.md` §1 (the `Domains` node used to hold per-part typed blocks).

## Why we changed it

Adding one part used to edit **four files** and repeat every param name in **five places**:

- `packages/ledger/schema.py` — a `*Domain` Pydantic class + a new `Optional[…] = None` field on `Domains`
- `packages/ledger/nodes.py` — dotted-path constants per param
- `packages/truth_plane/regen/templated.py` — a `render_*` function with matching kwargs
- `packages/subsystems/<part>.py` — fragment + `_check` + `_build` + `_volume` + `_seed` boilerplate + `register(...)` + bottom-import

Result: at 8 parts each subsystem file was ~140 lines of which ~90 were mechanical wrapper.
Projecting to 1000 parts: ~90 k lines of boilerplate + a `Domains` class with 1000 `Optional[...] = None` fields + `nodes.py` with 6000 constants. Every part edits three central files → collision point.

Worse, `StructureDomain` conflated a discipline (`material_profile`) with **bracket-specific**
geometry (`plate_width_mm`, `plate_depth_mm`, `skin_thickness_mm`, `internal_rib_spacing_mm`). So the
bracket's shape lived inside a discipline block while every other subsystem's shape lived in its own
typed block. Inconsistent.

## The new shape

**One source of truth per part** — a `ParamSpec` list — from which the ledger storage, dotted paths,
sliders, seeding, prompt param filter all derive.

### Ledger

```
MasterParametricLedger
├─ project_metadata        — has subsystem_type
├─ global_constraints
├─ domains
│   ├─ structure           — SMALL typed discipline (material_profile only)
│   ├─ manufacturing       — SMALL typed discipline (build_orientation, slip_fit)
│   ├─ thermal   (Optional) — SMALL typed discipline (operating_temp, power_dissipation)
│   └─ geometry            — GENERIC bag: dict[str, ParameterDef]
│                            keys named per active subsystem (skin_thickness_mm, box_width_mm, …)
│                            path: domains.geometry.<name>
├─ derived                 — solver outputs
└─ review
```

Disciplines stay typed (small, stable, named by solvers/gates). **Only subsystem geometry moved to
the generic dict** — that's the heterogeneous, proliferating axis.

### Subsystem + ParamSpec

```python
# packages/subsystems/base.py
@dataclass(frozen=True)
class ParamSpec:
    name: str
    value: float
    min: float
    max: float
    unit: str
    step: float | None = None
    label: str | None = None

@dataclass(frozen=True)
class Subsystem:
    name: str
    description: str
    fragment: str
    disciplines: tuple[str, ...]
    params: list[ParamSpec]
    build:      Callable[[Namespace], TaggedPart]
    volume:     Callable[[Namespace], float]
    invariants: Callable[[Namespace], list[str]]
```

`build`/`volume`/`invariants` receive a `Namespace` (attribute access on the resolved param values) —
nobody re-lists the param names.

### Full example — `packages/subsystems/washer.py` today (~50 lines total)

```python
WASHER = register_subsystem(Subsystem(
    name="washer",
    description="Flat annular washer/shim — FDM/FFF or stamped",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing", "thermal"),
    params=[
        ParamSpec("outer_dia_mm", value=20.0, min=6.0, max=60.0, unit="mm"),
        ParamSpec("inner_dia_mm", value=8.0,  min=2.0, max=50.0, unit="mm"),
        ParamSpec("thickness_mm", value=2.0,  min=0.8, max=10.0, unit="mm"),
    ],
    build=_build, volume=_volume, invariants=_check,
))
```

**Zero edits to `schema.py`, `nodes.py`, `templated.py`, `__init__.py`.** No `_pd`, no `_seed`,
no `WasherDomain`. Adding param #4 = one line in the `params` list.

## What derives from `params`

- **Ledger storage** → `Domains.geometry[name] = ParameterDef(...)` — built by walking `params` at genesis.
- **Dotted paths** → `f"domains.geometry.{name}"` — no per-part block in `nodes.py`.
- **`iter_parameters`** (`packages/ledger/branch.py`) walks typed BaseModel blocks AND the generic dict bag.
- **`apply.py::_resolve`** learned a terminal-dict-lookup branch: `domains.geometry.<name>` → dict lookup.
- **`/params` sliders + prompt param schema + `seed_defaults`** → single reader over the ParamSpec list.
- **subsystem-scoped prompt filter** → `subsystem.geometry_params ∪ cross-cutting disciplines`.

## Dual-use by design

Every registered `Subsystem` is inherently **both** (a) a standalone part in the top-level picker AND
(b) a callable component another subsystem's `build` invokes with per-instance overrides. A turbine
disc is a legitimate top-level part **and** a nested component. Same registration serves both roles —
no `library` role marker. Whether an entry appears in the picker UI is a rendering concern only.

Composition helpers for cross-subsystem invocation (`call(name, **overrides)`, `place`, `place_polar`,
tag namespacing) are **Phase F, deferred** until the first composite-of-registered-parts subsystem
actually needs them. Every subsystem is already dual-use by the base `Subsystem` shape.

## Migration (five phases, 155 tests green at every stop)

- **Phase A** — Parallel plumbing: `ParamSpec`, `Subsystem`, `Namespace`, `Domains.geometry`,
  `iter_parameters`/`_resolve` dict-aware, compat shim mapping old paths → new.
- **Phase B** — Migrated `washer` (proof of pattern).
- **Phase C** — Migrated `enclosure`, `standoff`, `lbracket`, `uchannel`, `panel`, `table`. Six
  `*Domain` classes + six `nodes.py` blocks deleted. Test fixtures (`seeded`, `seeded_with`) added
  in `tests/subsystems/conftest.py`.
- **Phase D** — Migrated `bracket` + untangled `StructureDomain`. Bracket geometry
  (skin/rib/plate/hole) moved out of `StructureDomain`/`ManufacturingDomain` and into the geometry
  bag. Batch-renamed ~155 test references from `domains.structure.<name>` / `domains.manufacturing.hole_diameter_mm`
  to `domains.geometry.<name>` via a two-pass regex (string paths, then Python attribute access).
- **Phase E** — Removed the compat shim; updated `deltas.py`, `demo_pipeline.py`,
  `frontend/src/types.ts`, `test_openrouter_provider.py`, docs, memory.

## Verified

- **155 backend tests + frontend typecheck** green at every phase boundary. Zero regressions.
- Live app still runs (`docker compose up` or dev via `uvicorn packages.transport.app:create_app
  --factory --host 127.0.0.1 --port 8001` + `npm run dev` under `packages/frontend`).
- End-to-end verified through the Vite proxy: subsystem picker, dynamic sliders, `/params`, `/mesh`,
  `/export/step` all follow the active subsystem via the same registry-driven adapter path.

## Adapter — how the new `Subsystem` reaches unchanged consumers

`packages/subsystems/__init__.py::register_subsystem(Subsystem)` wraps a `Subsystem` into the legacy
`SubsystemContext` shape that app.py, prompt_builder, and endpoint code already consume. Attributes:

- `fragment` → `prompt_fragment`
- `disciplines` → `applicable_disciplines`
- `params` (each ParamSpec name) → `geometry_params: tuple[f"domains.geometry.{name}"]`
- `build`/`volume`/`invariants` → wrapped with `resolve_namespace(sub, ledger)` (extracts geometry
  bag → `Namespace`)
- (new) `seed_defaults` → `seed_ledger_geometry` (populates the geometry bag from ParamSpec defaults)

No app.py/prompt_builder/endpoint changes were needed to consume the new subsystems.

## What's next (from the original plan roadmap)

Now that the subsystem axis is cheap:

1. **Cost discipline** — material + print-time → $ readout, lights up all 8 parts at once (highest leverage).
2. **More subsystems** — each is now one small file (turbine disc/blade/casing, hex standoff, box lid, gusset, tube…).
3. **Real CalculiX steady-state heat-transfer solver** — flip thermal L1 from `"unknown"` to grounded.
4. **Phase F composition helpers** — when the first cross-subsystem composite is needed.

## Files touched by the refactor

**New:**
- `packages/subsystems/base.py` (ParamSpec, Namespace, Subsystem, seed_ledger_geometry, resolve_namespace)
- `tests/subsystems/conftest.py` (seeded/seeded_with fixtures)

**Rewritten:**
- All 8 `packages/subsystems/<name>.py` files
- `packages/subsystems/__init__.py` (register_subsystem adapter)

**Slimmed:**
- `packages/ledger/schema.py` (`StructureDomain` now material_profile only; `ManufacturingDomain`
  drops hole_diameter_mm; 8 `*Domain` classes deleted; `Domains.geometry: dict[str, ParameterDef]` added)
- `packages/ledger/nodes.py` (bracket constants remap to `domains.geometry.*`; per-subsystem
  blocks deleted)
- `packages/ledger/apply.py` (`_set` helper for dict/attribute assignment; `_resolve` learned dict lookup)
- `packages/ledger/branch.py` (`iter_parameters` walks dict bags; `_set_param` uses `_set`)
- `packages/ledger/derived_resolver.py` (`GEOMETRY_PARAMS` points at `domains.geometry.*`)
- `packages/transport/app.py` (`make_core_ledger` slimmed; `current_params` reads geometry bag)
- `packages/truth_plane/demo_pipeline.py` (path renamed)
- `packages/frontend/src/types.ts` (SKIN/RIB/WIDTH/DEPTH/HOLE_DIA constants remap)

**Test-side path renames:** ~14 test files across `tests/{acceptance,backend,ledger,solvers,subsystems}/`.

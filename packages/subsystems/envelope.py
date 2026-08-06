"""Envelope resolver (2026-08-05, gearbox-housing-generation initiative Phase 2) — the arithmetic
behind a HOUSING instance's `wraps` list (`packages/ledger/schema.py::Instance.wraps`): derive a
housing's outer-envelope dimensions from the REAL, WORLD-PLACED geometry of whatever it's declared to
wrap, rather than an independently-guessed box (this initiative's own standing rule: never satisfy a
named capability like "enclosure" with a shallow stand-in). Mirrors `packages/subsystems/fit.py::
compute_fit`'s ok/reason/values discipline exactly, one layer out: a fit derives ONE connector's
dimension from ONE host's cross-section; an envelope derives ONE housing's outer dimensions from a
whole GROUP of wrapped member instances' actual built-and-placed geometry
(`packages/subsystems/geometry_query.py::group_world_bbox`/`group_convex_hull`, Phase 0).

Unlike `compute_fit` (pure closed-form arithmetic, no OCCT), `compute_envelope` DOES real OCCT work —
it calls Phase 0's `group_world_bbox`/`group_convex_hull`, both of which build and place every
member's real solid. That's still fine for this function to do directly, synchronously, as plain
Python: THIS module is pure/offline-testable (no async job, no REST route, no LLM) precisely so it can
be unit-tested against a synthetic ledger with zero HTTP/Dramatiq involved (see
`tests/subsystems/test_envelope.py`). Wiring it into a real async job so it never runs inline on a
request path is a LATER phase's job, not this one's — `packages/ledger/apply.py::apply_envelope_op`
deliberately never calls this function (see that function's own docstring).

HONEST v1 LIMITATION (stated here, NOT fixed in this phase — the real fix is a later phase's job):
`group_convex_hull` computes ONE global hull over EVERY member of `wraps` combined. For a housing
wrapping two separated sub-clusters (e.g. two gear stages sitting apart on a shaft train), a single
global hull bridges the gap between them with material that was never actually there in the waist
between the clusters — one smooth blob instead of a stepped shape that hugs each cluster separately.
The real fix is per-connected-component hulling (group members by proximity/connectivity first, hull
each component separately, then union the results) — deferred, not attempted here.

## Fix note (2026-08-06, R5 review, CONFIRMED, high) — SIZE was derived, POSITION never was

`envelope_socket` (Phase 2) only ever gave a housing its own outer SIZE (`hull_bbox_{x,y,z}_mm`) —
nothing derived, or ever set, the housing instance's own world POSITION. A housing sized exactly right
around its wraps group could still fail to physically CONTAIN it, the instant the housing's own
auto-layout/explicit-Transform position didn't happen to coincide with the group's own real position
(live-reproduced by R5: a housing correctly sized for two mesh-connected gears still let the second
gear poke ~5mm outside its own shell, because the housing sat centered on ITS OWN local origin while
the group's real centroid sat 15mm off of it; a housing landing in a LATER auto-layout slot, pushed
there by an ordinary, unrelated preceding part, showed ZERO world-bbox overlap with the shaft it
claimed to wrap). `derived_housing.py`'s own module docstring ("Two things this fix deliberately does
NOT attempt") had explicitly scoped this OUT as a separate, not-yet-approved feature — R5 confirmed
it is in fact part of this same defect, not a separate one: a housing whose position is never tied to
what it wraps cannot honestly be called "derived from" that group, only its size can.

Fixed here, not in a new module: `values` now ALSO always carries `coarse_bbox_center_{x,y,z}_mm` —
the midpoint of the ALREADY-computed `coarse_bbox` union AABB (zero extra OCCT cost) — and
`housing_alignment_transform` below turns that into the `Transform` a housing needs so its own LOCAL
origin (the point its `_dims`-derived shell/cavity is built symmetric around, see
`derived_housing.py::_dims`) lands exactly on the wrapped group's real world center. Both envelope-
derivation call sites (`packages/truth_plane/jobs.py::run_envelope_derivation`, the async job;
`packages/transport/app.py::_trigger_envelope_derivation`, the REDIS_URL-unset synchronous fallback)
now apply this alongside the existing size write, in the SAME all-or-nothing transaction — a housing's
position becomes just as "declared-derived, not guessed" as its size already was, the same posture
`FitSocketSpec`-driven connector dims already have."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from packages.ledger.schema import MasterParametricLedger, Transform


@dataclass(frozen=True)
class EnvelopeComputeResult:
    """The outcome of computing ONE housing's envelope. `ok=False` == "unknown" (with `reason`) —
    must block, never be treated as a pass (Inversion #1). `values` is a flat `dict[str, float]` of
    derived-dimension keys -> numbers, mirroring `FitComputeResult.values`'s own shape (there
    `connector_param -> computed value`; here just the derived KEYS themselves, since nothing writes
    through `EnvelopeSocketSpec.dim_params` in this phase — see `packages/subsystems/base.py::
    EnvelopeSocketSpec`'s own docstring for why).

    THREE families of keys, ALL always present together when `ok=True` (never partially — either the
    whole group's envelope resolves or it doesn't):

    - `coarse_bbox_x_mm` / `coarse_bbox_y_mm` / `coarse_bbox_z_mm`: the extents (size, not min/max) of
      the plain AABB union of every wrapped member's world-placed bounding box
      (`geometry_query.group_world_bbox`) — cheap, always computed, useful as a quick self-check
      baseline and a drift-check floor (the hull's own bbox can never be smaller than this on any
      axis).
    - `hull_bbox_x_mm` / `hull_bbox_y_mm` / `hull_bbox_z_mm`: the extents of the REAL convex hull
      solid's own bounding box (`geometry_query.group_convex_hull`) — the actual shape driver.
    - `coarse_bbox_center_x_mm` / `coarse_bbox_center_y_mm` / `coarse_bbox_center_z_mm` (2026-08-06,
      R5 fix — see this module's own docstring): the MIDPOINT of that same coarse AABB — the wrapped
      group's real world geometric center, zero extra OCCT cost (derived from the min/max this function
      already computes for `coarse_bbox_*` above). This is what `housing_alignment_transform` below
      aligns a housing's own local origin to; it is deliberately the coarse AABB's center, not the hull
      solid's own centroid — cheaper, and exactly as correct for "where does this group actually sit"
      purposes (a housing's own shell is itself an axis-aligned-in-cross-section box family, see
      `derived_housing.py::_dims`, so centering it on the group's bbox center is the right target, not
      a mass-weighted hull centroid).

    Storing the hull SOLID itself (rather than just its bbox extents) was considered and deliberately
    skipped for this phase: nothing downstream consumes a full solid yet (a later phase hasn't been
    built), so this keeps `values` a flat `dict[str, float]` like `FitComputeResult`'s own; a later
    phase that needs the actual hull shape re-derives it with a fresh `group_convex_hull(ledger,
    housing.wraps)` call (cheap to re-issue — `wraps` is already persisted on the housing Instance)
    rather than this result caching a copy that could silently drift from the ledger's current state."""

    ok: bool
    reason: Optional[str] = None
    values: dict[str, float] = field(default_factory=dict)


def compute_envelope(ledger: "MasterParametricLedger", housing_instance_id: str) -> EnvelopeComputeResult:
    """Derive `housing_instance_id`'s outer-envelope dimensions from the REAL, world-placed geometry of
    every instance it `wraps`. Read-only — never mutates the ledger or writes anything (same posture
    as `compute_fit`); the caller (a later phase's async job) is what would actually apply a result —
    `apply_envelope_op` (packages/ledger/apply.py) deliberately never calls this in this phase, see its
    own docstring."""
    from packages.subsystems import geometry_query, get_subsystem_model

    housing_inst = ledger.instances.get(housing_instance_id)
    if housing_inst is None:
        return EnvelopeComputeResult(ok=False, reason=f"housing instance {housing_instance_id!r} does not exist")

    try:
        housing_model = get_subsystem_model(housing_inst.subsystem_type)
    except KeyError:
        return EnvelopeComputeResult(ok=False, reason=f"unknown subsystem type {housing_inst.subsystem_type!r}")

    if housing_model.envelope_socket is None:
        return EnvelopeComputeResult(ok=False, reason=(
            f"{housing_inst.subsystem_type!r} declares no envelope_socket — it has no derived-"
            f"dimension mapping for anything wrapped to land in"))

    wraps = housing_inst.wraps
    if not wraps:
        return EnvelopeComputeResult(ok=False, reason=(
            f"{housing_instance_id!r}'s wraps list is empty — nothing to derive an envelope from"))

    missing = [iid for iid in wraps if iid not in ledger.instances]
    if missing:
        return EnvelopeComputeResult(ok=False, reason=(
            f"{housing_instance_id!r} wraps unknown instance id(s) {missing!r} — every member of "
            f"wraps must be a real instance in the ledger"))

    coarse_bbox = geometry_query.group_world_bbox(ledger, wraps)
    if coarse_bbox is None:
        return EnvelopeComputeResult(ok=False, reason=(
            f"none of {housing_instance_id!r}'s wraps members {wraps!r} produced buildable, "
            f"world-placeable geometry — cannot compute even a coarse bounding box"))

    hull = geometry_query.group_convex_hull(ledger, wraps)
    if hull is None:
        return EnvelopeComputeResult(ok=False, reason=(
            f"could not build a convex hull over {housing_instance_id!r}'s wraps members {wraps!r} "
            f"(need at least 4 non-coplanar tessellated points across the group) — a coarse bbox "
            f"alone is not a real shape driver"))

    (cx0, cy0, cz0), (cx1, cy1, cz1) = coarse_bbox
    hull_bbox = hull.bounding_box()

    values = {
        "coarse_bbox_x_mm": cx1 - cx0,
        "coarse_bbox_y_mm": cy1 - cy0,
        "coarse_bbox_z_mm": cz1 - cz0,
        "hull_bbox_x_mm": float(hull_bbox.size.X),
        "hull_bbox_y_mm": float(hull_bbox.size.Y),
        "hull_bbox_z_mm": float(hull_bbox.size.Z),
        # 2026-08-06 R5 fix (see this module's own docstring + EnvelopeComputeResult's own docstring):
        # the group's real world CENTER, not just its size — the missing input a housing needs to
        # align its own position to what it wraps, not merely be sized correctly for it.
        "coarse_bbox_center_x_mm": (cx0 + cx1) / 2.0,
        "coarse_bbox_center_y_mm": (cy0 + cy1) / 2.0,
        "coarse_bbox_center_z_mm": (cz0 + cz1) / 2.0,
    }
    return EnvelopeComputeResult(ok=True, values=values)


_CENTER_KEYS = ("coarse_bbox_center_x_mm", "coarse_bbox_center_y_mm", "coarse_bbox_center_z_mm")


def housing_alignment_transform(
    ledger: "MasterParametricLedger", housing_instance_id: str, result: EnvelopeComputeResult,
) -> Optional["Transform"]:
    """The `Transform` `housing_instance_id` needs so its own LOCAL origin — the point every one of its
    built solid's features (shell, cavity, bosses, foot corners; see `derived_housing.py::_dims`) is
    built symmetric around — lands exactly on `result`'s `coarse_bbox_center_{x,y,z}_mm` (the wrapped
    group's real world center, see `compute_envelope`'s own docstring). This is the missing half of
    `envelope_socket`'s own contract an R5 review (2026-08-06, CONFIRMED, high) found: SIZE alone does
    not make a housing actually contain what it wraps if its POSITION is untethered from it.

    Returns `None` — never a guessed/fallback Transform — when `result.ok` is False, the center keys
    aren't present (defensive only: `compute_envelope`'s own contract guarantees they're always present
    together with `coarse_bbox_*` whenever `ok=True`), or `housing_instance_id` isn't a real instance in
    `ledger`.

    `Instance.transform` is relative-to-PARENT (`packages/ledger/schema.py`), not always world-absolute
    — for the common case (`parent_id is None`, every existing `derived_housing` scenario in this
    codebase today) the two coincide; for a nested instance, the parent's own resolved world offset
    (`assembly.instance_world_offsets`) is read once and subtracted out first, so this stays correct
    regardless of nesting depth. Preserves whatever ROTATION the housing's CURRENT transform already
    carries (0.0 if it has none) — this function only ever aligns POSITION, it never introduces a
    rotation the caller didn't already have.

    Safe to call from an envelope-derivation context: `instance_world_offsets` may, to resolve the
    PARENT chain, end up building `housing_instance_id`'s own geometry once (if it has no explicit
    transform yet, to learn its own auto-layout Y-extent) — for `derived_housing` that calls back into
    `_housing_world_xy`'s OWN `extent_overrides`-guarded call to this same resolver, bounded to one
    extra level, never unbounded (see `derived_housing.py`'s own module docstring "recursion hazard"
    section; this function introduces no NEW hazard beyond one already designed around there)."""
    if not result.ok or any(k not in result.values for k in _CENTER_KEYS):
        return None
    housing = ledger.instances.get(housing_instance_id)
    if housing is None:
        return None

    from packages.ledger.schema import Transform

    target_x, target_y, target_z = (result.values[k] for k in _CENTER_KEYS)

    parent_id = housing.parent_id
    if parent_id is not None:
        from packages.subsystems.assembly import instance_world_offsets
        px, py, pz = instance_world_offsets(ledger).get(parent_id, (0.0, 0.0, 0.0))
    else:
        px = py = pz = 0.0

    current = housing.transform
    rx, ry, rz = (current.rx_deg, current.ry_deg, current.rz_deg) if current is not None else (0.0, 0.0, 0.0)
    return Transform(x_mm=target_x - px, y_mm=target_y - py, z_mm=target_z - pz,
                      rx_deg=rx, ry_deg=ry, rz_deg=rz)

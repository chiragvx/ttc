"""New-style scalable subsystem primitives (Phase A of the refactor).

Coexists with the legacy SubsystemContext during migration; both are exported from
packages/subsystems/__init__.py. See build-plan/reference/DOMAIN_TAXONOMY.md and
C:/Users/Chirag/.claude/plans/cosmic-herding-toucan.md for context.

A `Subsystem` is dual-use by design: the same registration serves BOTH (a) a standalone part someone
selects from the picker, AND (b) a callable component another subsystem's `build` invokes with
per-instance overrides. Composition helpers (call/place/place_polar) are Phase F — deferred.

The single source of truth per part is `Subsystem.params: list[ParamSpec]`. Everything the current
code repeats (schema class, node constants, render kwargs, seed values+bounds) DERIVES from this list.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Optional

from packages.ledger.parameter import ParameterDef, ParamSource

if TYPE_CHECKING:
    from packages.ledger.apply import CascadeRule
    from packages.ledger.schema import Instance, MasterParametricLedger, Transform


@dataclass(frozen=True)
class ParamSpec:
    """One tunable knob's declaration — the SINGLE source of truth for a subsystem's params.
    Materialised to a ledger `ParameterDef` by `Subsystem.defaults()`."""

    name: str
    value: float
    min: float
    max: float
    unit: str
    step: Optional[float] = None   # UI slider step (auto-derived from range if None)
    label: Optional[str] = None    # UI label (auto-derived from name if None)
    # 2026-08-01 (scoped MVP — a single passthrough tag, NOT a confidence-scoring system): where this
    # default value came from. "unsourced" (default) means every existing subsystem file that never
    # sets this keeps behaving exactly as today — purely descriptive, never read by `materialize()` or
    # any validation path.
    source: ParamSource = "unsourced"

    def materialize(self) -> ParameterDef:
        return ParameterDef(value=self.value, unit=self.unit, bounds=(self.min, self.max))


@dataclass(frozen=True)
class Frame:
    """A declared mate point in a part's OWN (unplaced, local) coordinates (Phase 1, 2026-07-19).
    `origin` is where the interface sits; `normal` is the outward direction its face points (unit-ish).
    Two mating faces touch with ANTI-PARALLEL normals — `wing_panel.root` points -X into the body,
    `bwb_fuselage.tip_right` points +X out of it — which is why a pre-oriented pair (e.g. `side_sign`
    already handles the wing's mirroring) mates with ZERO rotation, pure translation. `up` fully
    constrains orientation for the rotation-requiring mates deferred to Phase 1b; unused in v1.

    `radius` (2026-08-04, mesh-kind interfaces only): the PITCH radius at this axis, used ONLY by
    `kind="mesh"` interfaces (see `cylinder_axis_mesh_interface` below and
    `placement.py::resolve_mesh_mate`) — a "mount"/"containment"/"port" frame mates by COINCIDING
    origins, so it never needs a radius. None (default) means every existing mount/containment
    interface across the catalog is completely unaffected: zero behavior change."""

    origin: tuple[float, float, float]
    normal: tuple[float, float, float] = (1.0, 0.0, 0.0)
    up: Optional[tuple[float, float, float]] = None
    radius: Optional[float] = None


@dataclass(frozen=True)
class InterfaceSpec:
    """One declared interface (mate point) on a subsystem — the EKG 'interface' made typed. Its `frame`
    is a callable over the part's resolved params (like `build`/`volume`/`invariants`), so the mate
    point tracks the geometry: change `span_mm` and the wing-tip interface moves with it, and the
    placement solver re-mates automatically. `kind`: 'mount' (a part hangs off it), 'containment' (an
    envelope others sit inside — the body-vs-frame-dissolving edge), 'port' (a future coupling attach
    point, Phase 2).

    `keepout_mm` (2026-07-22, mechanism only — no subsystem sets this yet): a clearance radius this
    interface needs kept clear of any OTHER instance's geometry (e.g. a sensor that needs an
    unobstructed cone/volume in front of its mount face). Checked by
    `packages/truth_plane/validate.py`'s "keepout" check via `placement.py::world_frame_for_interface`.
    Deciding WHICH parts need how much clearance is a domain-semantic judgment (what "line of sight"
    means for a given part) deliberately deferred — this field exists so that judgment has somewhere
    to plug in later without a schema change. 0.0 (default) = no keepout requirement."""

    name: str
    kind: str  # "mount" | "containment" | "port"
    frame: Callable[["Namespace"], Frame]
    keepout_mm: float = 0.0


@dataclass(frozen=True)
class FitProfile:
    """The cross-section a HOST subsystem presents to whatever might be fitted around/to it (2026-07-27
    — the missing dimensional data `Frame`/`InterfaceSpec` never carried, confirmed absent by direct
    reading before this was added). A pure value, read fresh from the host's own resolved params every
    time a fit is computed or re-verified — never stored anywhere itself (see `FitBinding` in
    packages/ledger/schema.py and `packages/subsystems/fit.py::compute_fit`).

    `kind` discriminates what `dims` means, so a connector that only understands one kind refuses the
    fit outright rather than guessing: `"round"` -> `{"dia_mm": ...}`; `"rect"` -> `{"width_mm": ...,
    "height_mm": ...}`. Adding a third kind later is additive (a new discriminated branch), never a
    redesign of this type."""

    kind: str
    dims: dict[str, float]


@dataclass(frozen=True)
class FitSocketSpec:
    """A CONNECTOR subsystem's declaration of what it needs fitted, and where the computed result
    should land (2026-07-27). `kind` must match the HOST `FitProfile.kind` it gets wired to at
    `fit_connector` time (packages/ledger/apply.py) — a mismatch is refused, never coerced (a round
    bore fitted onto a rect host is not "close enough", it's a part that doesn't fit).

    `dim_params` maps each dimension role the kind implies to this connector's OWN `ParamSpec` name
    that receives `host_value + clearance_mm` — e.g. round: `{"dia_mm": "bore_dia_mm"}`; rect:
    `{"width_mm": "bore_width_mm", "height_mm": "bore_height_mm"}`. The connector keeps these as
    ordinary, independently-bounded params — `fit_connector` writes them through the SAME
    `apply_delta` path any hand-typed dimension uses, so a fitted connector's `_build` never needs to
    know a fit mechanism exists; it just reads its own params like always."""

    kind: str
    dim_params: dict[str, str]


@dataclass(frozen=True)
class EnvelopeSocketSpec:
    """A HOUSING subsystem's declaration of which derived-dimension keys `compute_envelope`
    (packages/subsystems/envelope.py) can produce, and where each one WOULD land among this
    subsystem's OWN `ParamSpec`s (2026-08-05, gearbox-housing-generation initiative Phase 2) --
    mirrors `FitSocketSpec` exactly in shape and doc style, one layer further out: a fit derives a
    CONNECTOR's dimension from a single HOST's own cross-section; an envelope derives a HOUSING's own
    outer dimensions from the convex hull of a whole GROUP of wrapped member instances
    (`Instance.wraps`, packages/ledger/schema.py).

    `dim_params` maps each derived-dimension KEY `EnvelopeComputeResult.values` can return (e.g.
    `"hull_bbox_x_mm"`/`"hull_bbox_y_mm"`/`"hull_bbox_z_mm"` -- see `compute_envelope`'s own docstring
    for the full key set) to this housing's OWN `ParamSpec` name that would receive it -- e.g.
    `{"hull_bbox_x_mm": "outer_width_mm", "hull_bbox_y_mm": "outer_depth_mm", "hull_bbox_z_mm":
    "outer_height_mm"}`. UNLIKE `FitSocketSpec.dim_params`, nothing writes through this mapping yet in
    this phase -- `apply_envelope_op` (packages/ledger/apply.py) only ever writes `Instance.wraps` (a
    cheap, ordinary ledger mutation); wiring a `compute_envelope` result through this socket into real
    ParamSpec values is real multi-instance OCCT work, deliberately deferred (never run synchronously
    inline on an apply/request path, per this initiative's own async-job rule -- see
    `compute_envelope`'s own module docstring). This field exists now so that later wiring has a
    typed, catalog-declared place to plug into -- the same "declare now, consume later" precedent
    `FitSocketSpec` itself set when it first landed."""

    dim_params: dict[str, str]


def cylinder_end_interfaces(height_param: str, names: tuple[str, str] = ("bottom", "top")) -> list[InterfaceSpec]:
    """Two mount interfaces at the +/- ends of a subsystem's own local Z axis (2026-07-27) — the
    missing complement to `bar_end_interfaces` above, for the CYLINDER shape family instead of the
    box-bar family: `round_post`/`round_bar`/`standoff`/`spar_joiner_sleeve`/etc, all built as
    `bd.Cylinder(radius=..., height=p.<height_param>)`, which build123d centers on the origin along
    local Z BY DEFAULT (unlike a Box-family bar, which needs an explicit rotation to stand upright —
    confirmed live this session: round_post/round_bar are used vertically with NO rotation, in
    contrast to the box-bar family's own general-rule rotation requirement). `normal` points OUTWARD
    from each end, matching `Frame`'s own anti-parallel-touching-normals mating convention (a post
    stacked on another post: one's `top` normal is +Z, the other's `bottom` normal is -Z).

    NOT for a part whose cylinder axis runs along a different local axis, or a non-cylindrical part —
    confirm the actual `_build` orientation before reusing this on a new file."""
    def _end(sign: float) -> Callable[["Namespace"], Frame]:
        def _frame(p: "Namespace") -> Frame:
            half = getattr(p, height_param) / 2.0
            return Frame(origin=(0.0, 0.0, sign * half), normal=(0.0, 0.0, sign))
        return _frame
    name_bottom, name_top = names
    return [InterfaceSpec(name=name_bottom, kind="mount", frame=_end(-1.0)),
            InterfaceSpec(name=name_top, kind="mount", frame=_end(1.0))]


def cylinder_axis_mesh_interface(dia_param: str, name: str = "mesh") -> InterfaceSpec:
    """ONE `kind="mesh"` interface at a subsystem's own local origin, for the SAME centered-cylinder
    shape family `cylinder_end_interfaces` above targets (`gear_blank`/`pinion_blank`/`sprocket_blank`/
    etc, `bd.Cylinder(radius=..., height=...)`, centered at the origin, standing along local Z BY
    DEFAULT — confirm the actual `_build` before reusing this on a new file, same discipline as
    `cylinder_end_interfaces`). Unlike that helper (which marks the two flat END faces, for AXIAL
    stacking), this marks the part's own ROTATION AXIS for RADIAL (parallel-axis gear mesh) mating:
    `origin=(0, 0, 0)` (the local origin IS the axis, by the same centered-cylinder construction),
    `normal=(0, 0, 1)` (the axis direction, Z-up — see the v1 scope limit below), and `radius` set to
    the PITCH radius: half of the named diameter param (`dia_param`), read fresh from the part's own
    resolved params exactly like every other frame in this file (`radius = getattr(p, dia_param) / 2.0`).

    `kind="mesh"` (never `"mount"`) is deliberate: `placement.py`'s ordinary coincident-origin/
    anti-parallel-normal mount solver does NOT understand this interface — two gears mesh with their
    centers held `radius_a + radius_b` APART, not coincident. Only
    `placement.py::resolve_mesh_mate` interprets a `kind="mesh"` interface; everything else in this
    file keeps treating `kind` as an opaque, unvalidated str (deliberately NOT upgraded to a `Literal`
    here — that would be an unrelated, out-of-scope cleanup of the ~86 existing `kind="mount"` call
    sites too).

    HONEST LIMITATION (v1 scope, matches `placement.py::resolve_mesh_mate`'s own docstring): only
    SAME-Z-AXIS (planar) meshing is supported — `normal` is unconditionally `(0, 0, 1)`, so this helper
    has no way to represent a gear whose rotation axis isn't world/local Z. Arbitrary 3D mesh axes
    (a bevel or worm gear meshing at an angle) are explicitly OUT OF SCOPE — do not reuse this helper
    for that case; it would silently build a "mesh" interface with the wrong axis, not an error."""
    def _frame(p: "Namespace") -> Frame:
        return Frame(origin=(0.0, 0.0, 0.0), normal=(0.0, 0.0, 1.0), radius=getattr(p, dia_param) / 2.0)
    return InterfaceSpec(name=name, kind="mesh", frame=_frame)


def bar_end_interfaces(length_param: str, names: tuple[str, str] = ("end_a", "end_b")) -> list[InterfaceSpec]:
    """Two mount interfaces at the +/- ends of a subsystem's own local X axis (2026-07-20) — generic
    for ANY subsystem whose `_build` centers a plain box along local X using one named length param
    (the `longeron`/`tail_boom`/`flat_bar`/`wing_spar`/`stabilizer_spar`/gear-leg shape family:
    `bd.Box(length_mm, width_mm, height_mm)`, centered at the origin by construction — confirmed by
    reading each of those files directly before reusing this). `normal` points OUTWARD from each end,
    matching `Frame`'s own anti-parallel-touching-normals mating convention (two bars meeting end to
    end: one's `end_b` normal is +X, the other's `end_a` normal is -X).

    NOT for a plate/L-bracket-shaped part (e.g. `motor_mount_firewall`, `wing_root_fitting`) — those
    use a different local-frame convention (a face, not a bar end) and aren't covered by this helper."""
    def _end(sign: float) -> Callable[["Namespace"], Frame]:
        def _frame(p: "Namespace") -> Frame:
            half = getattr(p, length_param) / 2.0
            return Frame(origin=(sign * half, 0.0, 0.0), normal=(sign, 0.0, 0.0))
        return _frame
    name_a, name_b = names
    return [InterfaceSpec(name=name_a, kind="mount", frame=_end(-1.0)),
            InterfaceSpec(name=name_b, kind="mount", frame=_end(1.0))]


def plate_face_interfaces(thickness_param: str, names: tuple[str, str] = ("top", "bottom")) -> list[InterfaceSpec]:
    """Two mount interfaces at the +/- Z faces of a subsystem's own local Z axis (2026-07-20) —
    generic for any subsystem whose `_build` centers a plain `width x depth x thickness` box at the
    origin using one named thickness param (the `packages/truth_plane/regen/templated.py::render_bracket`
    -derived plate/tray shape family — `motor_mount_firewall`, `avionics_tray`, `battery_bay_divider`,
    `battery_strap_mount`, `servo_mount_tray`, confirmed by reading each file directly before reuse;
    many other catalog entries share the same archetype and could adopt this the same way once
    verified). `normal` points OUTWARD from each face, matching `Frame`'s anti-parallel-normals
    mating convention. Mirrors `bar_end_interfaces` for the plate/tray shape family instead of bars."""
    def _face(sign: float) -> Callable[["Namespace"], Frame]:
        def _frame(p: "Namespace") -> Frame:
            half = getattr(p, thickness_param) / 2.0
            return Frame(origin=(0.0, 0.0, sign * half), normal=(0.0, 0.0, sign))
        return _frame
    name_a, name_b = names
    return [InterfaceSpec(name=name_a, kind="mount", frame=_face(1.0)),
            InterfaceSpec(name=name_b, kind="mount", frame=_face(-1.0))]


_BOX_FACE_AXIS: dict[str, tuple[float, float, float]] = {
    "left": (1.0, 0.0, 0.0), "right": (1.0, 0.0, 0.0),
    "front": (0.0, 1.0, 0.0), "back": (0.0, 1.0, 0.0),
    "bottom": (0.0, 0.0, 1.0), "top": (0.0, 0.0, 1.0),
}
_BOX_FACES: tuple[tuple[str, float], ...] = (
    ("left", -1.0), ("right", 1.0), ("front", -1.0), ("back", 1.0), ("bottom", -1.0), ("top", 1.0),
)


def box_face_interfaces(width_param: str, depth_param: str, height_param: str) -> list[InterfaceSpec]:
    """Six mount interfaces at the +/- faces of a subsystem's own local X/Y/Z axes (2026-07-22) —
    generic for any subsystem whose `_build` centers a plain width x depth x height box at the origin
    using three named dimension params (confirmed for `enclosure`'s outer box shell by reading the
    file directly before reuse — `bd.Box(box_width_mm, box_depth_mm, box_height_mm)`, centered at the
    origin by construction; `enclosure`'s lid is a SEPARATE body shifted off in +Y purely for
    print-bed visual separation and is NOT one of these six — they describe the box shell only).
    Named by a fixed physical convention — width axis is left(-X)/right(+X), depth axis is
    front(-Y)/back(+Y), height axis is bottom(-Z)/top(+Z) — so a part "mounted on the side" has an
    unambiguous, LLM-readable target. `normal` points OUTWARD from each face, matching `Frame`'s
    anti-parallel-normals mating convention. Unlike `plate_face_interfaces` (2 faces, thin plate) or
    `bar_end_interfaces` (2 faces, bar ends) this covers all 6 box faces since a box-shaped mount
    target (an enclosure, a case) can have parts mounted on any side, not just top/bottom.

    HONEST LIMITATION shared with every interface pair in this v1 (translation-only mating, rotation
    deferred to Phase 1b — see placement.py's module docstring): a directional part with a FIXED local
    mount-face normal (e.g. `lbracket`'s `wall_mount`, always -X) only mates CLEANLY here against the
    ONE face whose own outward normal is anti-parallel to it (for `wall_mount`, that's `right`) —
    connecting it to a different face still resolves a translation but leaves the part facing the
    wrong way, surfaced only as an advisory `connections`-check warning, not a hard rejection."""
    param_by_axis = {"x": width_param, "y": depth_param, "z": height_param}

    def _frame_for(sign: float, unit: tuple[float, float, float]) -> Callable[["Namespace"], Frame]:
        axis = "x" if unit[0] else ("y" if unit[1] else "z")
        param = param_by_axis[axis]

        def _frame(p: "Namespace") -> Frame:
            half = getattr(p, param) / 2.0
            return Frame(origin=tuple(sign * half * c for c in unit),
                         normal=tuple(sign * c for c in unit))
        return _frame

    return [InterfaceSpec(name=name, kind="mount", frame=_frame_for(sign, _BOX_FACE_AXIS[name]))
            for name, sign in _BOX_FACES]


def lbracket_interfaces(
    leg_a_param: str, leg_b_param: str, thickness_param: str,
    names: tuple[str, str] = ("wall_mount", "top"),
) -> list[InterfaceSpec]:
    """Two mount interfaces for the `render_lbracket`-shaped part family (2026-07-22): a vertical
    flange (`leg_a`, running local +Z from the shared corner) and a horizontal flange (`leg_b`,
    running local +X from the corner), confirmed against
    `packages/truth_plane/regen/templated.py::render_lbracket` directly — `base` occupies x in
    [0,leg_b], z in [0,t]; `wall` occupies x in [0,t], z in [0,leg_a]; both centered on y.
    `wall_mount` is the OUTER face of the vertical flange (x=0, normal -X) — the face that bolts flat
    against whatever this bracket mounts TO. `top` is the OUTER (upper) face of the horizontal flange
    (z=thickness, normal +Z) — where a carried part/payload sits.

    Applied to `lbracket` itself only (fully verified) — NOT yet applied to the ~36 other catalog
    subsystems that reuse the same `render_lbracket` builder under their own param names/proportions
    (`angle_iron`, `servo_bracket`, `wing_root_fitting`, ...); each would need its own param names
    confirmed before adopting this, same "verify before reuse" discipline as `plate_face_interfaces`.

    ONE HONEST LIMITATION (v1 translation-only mating — see `box_face_interfaces`'s docstring for the
    general case): `wall_mount`'s normal is fixed at -X, so it only mates CLEANLY against a box-shaped
    target's `right` face (the one face with an anti-parallel +X normal) — a different face still
    silently translates without correcting orientation, surfaced only as an advisory warning."""
    def _wall_mount(p: "Namespace") -> Frame:
        return Frame(origin=(0.0, 0.0, getattr(p, leg_a_param) / 2.0), normal=(-1.0, 0.0, 0.0))

    def _top(p: "Namespace") -> Frame:
        return Frame(origin=(getattr(p, leg_b_param) / 2.0, 0.0, getattr(p, thickness_param)),
                     normal=(0.0, 0.0, 1.0))

    name_wall, name_top = names
    return [InterfaceSpec(name=name_wall, kind="mount", frame=_wall_mount),
            InterfaceSpec(name=name_top, kind="mount", frame=_top)]


class Namespace:
    """Attribute-access facade over a subsystem's resolved param values. `p.top_width_mm` returns the
    float value. Passed to build/volume/invariants so nobody re-lists the param names."""

    __slots__ = ("_params",)

    def __init__(self, params: dict[str, ParameterDef]) -> None:
        self._params = params

    def __getattr__(self, name: str) -> float:
        pd = self._params.get(name)
        if pd is None:
            raise AttributeError(f"no such param: {name!r}")
        return pd.value

    def __repr__(self) -> str:
        body = ", ".join(f"{k}={v.value}" for k, v in self._params.items())
        return f"Namespace({body})"


def _empty_invariants(p: Namespace) -> list[str]:
    return []


@dataclass(frozen=True)
class ChildSpec:
    """One desired CHILD instance of an assembly-template `Subsystem` (see
    `Subsystem.assembly_children`), as returned from the master namespace by that callable.

    `local_id` becomes part of the real Instance id in the ledger tree (`f"{root_id}_{local_id}"`,
    see `packages/subsystems/assembly_template.py::reconcile_children`) — it must NEVER contain a
    "." character. Instance ids are addressed via dotted paths elsewhere
    (`instances.<id>.params.<name>`, parsed by a naive `path.split(".")` in
    `packages/ledger/apply.py::_resolve`), so a literal dot in an id breaks addressing. Use plain
    alphanumeric/underscore local ids (e.g. "top", "leg0", "leg1"), not bracketed or dotted forms.
    """

    local_id: str
    subsystem_type: str
    transform: "Transform"
    params: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if "." in self.local_id:
            raise ValueError(f"ChildSpec.local_id must not contain '.': {self.local_id!r}")


@dataclass(frozen=True)
class Subsystem:
    """A self-describing part: the ENTIRE per-part surface for the scalable model.

    Adding a subsystem = ONE file in packages/subsystems/<name>.py that creates a Subsystem and calls
    the registrar. Zero central edits — schema.py, nodes.py, templated.py, __init__.py stay untouched
    (once the Phase A plumbing lands).
    """

    name: str
    description: str
    fragment: str                              # LLM knowledge fragment (part-specific)
    disciplines: tuple[str, ...]               # applicable discipline lenses
    params: list[ParamSpec] = field(default_factory=list)
    build: Optional[Callable[[Namespace], object]] = None      # (p) -> TaggedPart
    # 2026-08-06 (gearbox-housing-generation initiative Phase 5 / Stage 2) -- an ADDITIVE, LEDGER-AWARE
    # build hook alongside `build` above. None (default) = every existing subsystem (all ~270 of them)
    # is completely unaffected -- `register_subsystem`'s own `_build` closure
    # (packages/subsystems/__init__.py) tries THIS first (when set) and only falls back to the ordinary
    # `build(namespace)` call otherwise. Signature carries the full ledger + this instance's own
    # resolved id (not just the Namespace) because a housing's Stage-2 features (bearing bosses/oil-
    # seal grooves at a wrapped member's REAL WORLD position) need `Instance.wraps` + a way to read
    # another instance's own world position -- see `derived_housing.py`'s own module docstring for the
    # concrete motivating case, INCLUDING a real recursion hazard (this subsystem's own build calling
    # back into whole-ledger auto-layout, which can call back into this subsystem's own build) that a
    # careful implementer of this hook must design around. A subsystem that sets this should still keep
    # `build` too, as a ledger-free fallback (used by e.g. `compose.py::call()`), unless it genuinely
    # has none to offer.
    build_with_ledger: Optional[Callable[["MasterParametricLedger", str, Namespace], object]] = None
    volume: Optional[Callable[[Namespace], float]] = None      # (p) -> float mm^3
    invariants: Callable[[Namespace], list[str]] = field(default=_empty_invariants)
    # 2026-07-03 (FEA coverage expansion): True only for single-solid, plate/bar-shaped parts where
    # the EXISTING validated cantilever methodology (clamp one end, load the other, see
    # packages/truth_plane/solvers/{mesh,fs}.py) is a faithful re-use, not a new physics claim. False
    # (default) means the part's FS honestly stays "unknown" — never a fabricated load case. See
    # build-plan/reference/ and packages/truth_plane/CLAUDE.md: FEA methodology is FEA-engineer
    # territory; this flag is deliberately opt-in per subsystem, not inferred.
    fea_eligible: bool = False
    # 2026-07-16 (min-wall floor gap found in the 2026-07-14 audit): packages/truth_plane/analysis.py's
    # `_min_wall_ok` discovers a part's print-limiting dimension(s) by naming CONVENTION — any param
    # ending in `thickness_mm`. That's right for a plate/bar whose thin dimension IS named that way, but
    # wrong for a subsystem like `longeron` whose cross-section is `width_mm`/`height_mm` — the
    # convention finds nothing, so the check silently no-ops (always True) no matter how thin the part
    # actually is. Empty (default) = use the naming convention, unaffected. Non-empty = these EXACT
    # param names are checked against the floor instead of guessing from the name — set this only when
    # the naming convention would otherwise miss the part's real thin dimension(s).
    min_wall_params: tuple[str, ...] = ()
    # 2026-07-03 (cascade deltas, prd4.md §2.2): an OPTIONAL packages.ledger.apply.CascadeRule this
    # subsystem declares — e.g. growing a bolt hole past the edge-distance rule cascades the plate
    # depth up instead of outright rejecting the request. None (default) = no cascades for this part.
    cascades: Optional["CascadeRule"] = None
    # 2026-07-03 (assembly-template mechanism): an OPTIONAL callable that turns this subsystem's
    # resolved master params into a list[ChildSpec] of desired CHILD instances — real siblings in the
    # ledger's instance tree (see packages/subsystems/assembly_template.py::reconcile_children), not
    # fused geometry. A subsystem that sets this should also leave `build=None`: it has no geometry
    # of its own, it's an organizational/master-param node whose children carry the real geometry.
    # None (default) = an ordinary subsystem, unaffected — reconcile_children() is a no-op for it.
    assembly_children: Optional[Callable[[Namespace], list["ChildSpec"]]] = None
    # 2026-07-19 (airframe-first pacing): True only for a part that sets the vehicle's own outer mold
    # line / overall silhouette — a wing or fuselage-class body (naca_wing, bwb_fuselage,
    # tube_fuselage, ogive_fuselage, winged_fuselage, lofted_spindle/lofted_hull when used as a body).
    # `packages/agents/prompt_builder.py` reads this (via every registered subsystem, not a hardcoded
    # name list) to decide whether a file's shape is established yet, and paces a vague whole-vehicle
    # request accordingly (propose the airframe alone first, ask before adding systems/mounting
    # parts) — see that file's own "airframe-first pacing" section for the full rule. False (default)
    # means an ordinary systems/structural/mounting part — same deliberately-opt-in-per-subsystem
    # stance as `fea_eligible`, not inferred from shape or size.
    is_airframe_defining: bool = False
    # 2026-07-19 (Phase 1 — interfaces + connections): declared mate points on this part. A part with
    # interfaces can be joined to another via a typed `Connection`, and the placement solver
    # (packages/subsystems/placement.py) derives its Transform from the mate instead of the LLM
    # computing coordinates. Empty (default) = an ordinary part with no declared mate points; nothing
    # changes for it. See InterfaceSpec / Frame above and ENGINEERING_GRAPH_ARCHITECTURE.md §1.
    interfaces: list["InterfaceSpec"] = field(default_factory=list)
    # 2026-07-27 (fitted-joint mechanism) — HOST side: a callable deriving this part's own
    # FitProfile (its cross-section) from its own resolved params, same contract as `frame` above.
    # None (default) = this part can't be fitted TO by anything.
    fit_profile: Optional[Callable[[Namespace], "FitProfile"]] = None
    # 2026-07-27 — CONNECTOR side: this part's declared socket, naming which of ITS OWN params
    # receive a wired fit's computed dimensions. None (default) = this part has no fittable socket.
    fit_socket: Optional["FitSocketSpec"] = None
    # 2026-08-05 (gearbox-housing-generation initiative Phase 2) -- HOUSING side: which derived-
    # dimension keys a `compute_envelope` result can feed into this subsystem's OWN params, and under
    # what names (see `EnvelopeSocketSpec` above). None (default) = this part is not a housing-family
    # subsystem -- `Instance.wraps` (packages/ledger/schema.py) is meaningless/ignored for it. No
    # subsystem in the catalog declares this yet; a later phase is the first real consumer.
    envelope_socket: Optional["EnvelopeSocketSpec"] = None

    def defaults(self) -> dict[str, ParameterDef]:
        """Materialised ParameterDefs keyed by name — used to seed the ledger's geometry bag."""
        return {p.name: p.materialize() for p in self.params}


_ROOT_ID = "root"


def geometry_paths(subsystem: Subsystem, instance_id: str) -> tuple[str, ...]:
    """The dotted ledger paths for `subsystem`'s params AT a specific instance occurrence. A
    `Subsystem` is a TYPE; an `Instance` is an OCCURRENCE (Phase G) — two instances of the same type
    (e.g. two `standoff`s in one project) have the same param NAMES but different dotted PATHS."""
    return tuple(f"instances.{instance_id}.params.{p.name}" for p in subsystem.params)


def seed_instance(subsystem: Subsystem, instance_id: str, parent_id: Optional[str] = None) -> "Instance":
    """Materialise a fresh Instance of `subsystem`'s type, seeded with its ParamSpec defaults. Used
    both for genesis (root instance) and for adding a new instance to an existing project (Item 3
    outliner)."""
    from packages.ledger.schema import Instance
    return Instance(id=instance_id, subsystem_type=subsystem.name,
                    params=subsystem.defaults(), parent_id=parent_id)


def seed_ledger_geometry(subsystem: Subsystem, ledger: "MasterParametricLedger") -> "MasterParametricLedger":
    """Seed a single-instance project rooted at this subsystem — params go into the instance tree
    (`instances["root"].params`), which is the Phase G source of truth."""
    root = seed_instance(subsystem, _ROOT_ID, parent_id=None)
    return ledger.model_copy(update={"instances": {_ROOT_ID: root}, "root_id": _ROOT_ID})


def resolve_namespace(
    subsystem: Subsystem,
    ledger: "MasterParametricLedger",
    instance_id: Optional[str] = None,
) -> Namespace:
    """Build a Namespace from `instance_id`'s params (default: the ledger's ROOT instance — preserves
    every pre-Item-3 call site unchanged), filtered to this subsystem's declared params. Missing
    params fall back to the ParamSpec default."""
    iid = instance_id if instance_id is not None else ledger.root_id
    inst = ledger.instances.get(iid) if ledger.instances else None
    bag = inst.params if inst is not None else {}
    resolved: dict[str, ParameterDef] = {}
    for spec in subsystem.params:
        pd = bag.get(spec.name)
        resolved[spec.name] = pd if pd is not None else spec.materialize()
    return Namespace(resolved)

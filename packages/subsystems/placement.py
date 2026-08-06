"""Mate solver (Phase 1, 2026-07-19) — derive each connected instance's world `Transform` from the
typed `Connection`s that join its interfaces, instead of the copilot hand-computing coordinates. This
is the payoff of interfaces+connections: the sweep/dihedral offset a wing needs is read off the body's
own declared tip frame (packages/subsystems/bwb_fuselage.py `_tip_frame`), never trig the LLM gets wrong.

**v1 scope, deliberate and honest (ENGINEERING_GRAPH_PLAN.md P1):** mates are computed as PURE
TRANSLATION — position the not-yet-placed part so its interface origin coincides with its partner's
(plus any `gap_mm` along the mate normal). This is exact and verifiable for pre-oriented pairs (a
`wing_panel`'s `side_sign` already mirrors it, so its `root` normal is anti-parallel to a body tip's
with ZERO rotation). A mate that would need a NON-identity rotation is NOT auto-solved here — it is
flagged by `connection_issues()` (the copilot supplies an explicit transform for now); auto-solving
arbitrary mate rotations (matrix→Euler) is Phase 1b, kept out until it can be verified against build123d
rather than trusted on paper (the session's repeated rotation bugs earned that caution).

Pure python — no build123d, no solver — so this runs on the interactive/closed-form tier. The one piece
of real 3D math (applying a Transform's rotation to a frame) uses build123d's VERIFIED
`Rotation(rx,ry,rz) == Rx·Ry·Rz` convention (checked empirically 2026-07-19)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from packages.subsystems import get_subsystem_model
from packages.subsystems.base import Frame, InterfaceSpec, resolve_namespace

if TYPE_CHECKING:
    from packages.ledger.schema import InterfaceRef, MasterParametricLedger, Transform

_ANTIPARALLEL_TOL = 1e-3  # dot(n_a, -n_b) must be ~1 for a v1 (rotation-free) mate


def _rot_apply(rx_deg: float, ry_deg: float, rz_deg: float, v: tuple[float, float, float]):
    """Rotate `v` by build123d's `Rotation(rx,ry,rz)` — the matrix product Rx·Ry·Rz applied to the
    vector, i.e. Rz first, then Ry, then Rx (VERIFIED empirically against build123d 2026-07-19:
    R(90,90,0)·(1,0,0) == (0,1,0))."""
    if not (rx_deg or ry_deg or rz_deg):
        return v
    ax, ay, az = math.radians(rx_deg), math.radians(ry_deg), math.radians(rz_deg)
    x, y, z = v
    cz, sz = math.cos(az), math.sin(az)
    x, y = cz * x - sz * y, sz * x + cz * y          # Rz
    cy, sy = math.cos(ay), math.sin(ay)
    x, z = cy * x + sy * z, -sy * x + cy * z          # Ry
    cx, sx = math.cos(ax), math.sin(ax)
    y, z = cx * y - sx * z, sx * y + cx * z            # Rx
    return (x, y, z)


def _apply_transform_to_frame(t: "Transform", frame: Frame) -> Frame:
    """A part's LOCAL interface frame → its WORLD frame, given the part's world Transform. Rotate both
    origin and normal by the transform's rotation, then translate the origin (a normal is a direction,
    not translated)."""
    ox, oy, oz = _rot_apply(t.rx_deg, t.ry_deg, t.rz_deg, frame.origin)
    return Frame(
        origin=(ox + t.x_mm, oy + t.y_mm, oz + t.z_mm),
        normal=_rot_apply(t.rx_deg, t.ry_deg, t.rz_deg, frame.normal),
    )


def _local_frame(ledger: "MasterParametricLedger", instance_id: str, interface: str) -> Optional[Frame]:
    inst = ledger.instances.get(instance_id)
    if inst is None:
        return None
    try:
        model = get_subsystem_model(inst.subsystem_type)
    except KeyError:
        return None
    spec = next((s for s in model.interfaces if s.name == interface), None)
    if spec is None:
        return None
    return spec.frame(resolve_namespace(model, ledger, instance_id))


def _adjacency(ledger: "MasterParametricLedger"):
    """instance_id -> list of (neighbor_id, my_interface, neighbor_interface, gap_mm) for every valid
    connection (both endpoints exist and name a real interface)."""
    adj: dict[str, list] = {iid: [] for iid in ledger.instances}
    for c in ledger.connections:
        a, b = c.a, c.b
        if a.instance_id not in ledger.instances or b.instance_id not in ledger.instances:
            continue
        if _local_frame(ledger, a.instance_id, a.interface) is None:
            continue
        if _local_frame(ledger, b.instance_id, b.interface) is None:
            continue
        adj[a.instance_id].append((b.instance_id, a.interface, b.interface, c.gap_mm))
        adj[b.instance_id].append((a.instance_id, b.interface, a.interface, c.gap_mm))
    return adj


def _identity_transform() -> "Transform":
    from packages.ledger.schema import Transform
    return Transform()


def _connected_components(adj: dict[str, list]) -> list[list[str]]:
    """Connected components of the graph `_adjacency` describes, as (sorted) member-id lists, ordered by
    each component's own minimum id (repeatedly peel off `min(remaining)`, then BFS/stack out via
    adjacency). The SINGLE shared implementation for `resolve_placements`'s per-component datum/BFS setup
    and `unanchored_components`'s own component scan — previously each carried its own textually-identical
    copy of this BFS/stack loop, a DRY hazard the reviewer confirmed: a future change to component-
    detection semantics (e.g. how `_adjacency` neighbors are walked) made in only one copy could make the
    mate solver and the collision-avoidance packer partition the same connection graph differently."""
    connected = {iid for iid, nbrs in adj.items() if nbrs}
    remaining = set(connected)
    out: list[list[str]] = []
    while remaining:
        comp_seed = min(remaining)
        comp: set[str] = set()
        stack = [comp_seed]
        while stack:
            cur = stack.pop()
            if cur in comp:
                continue
            comp.add(cur)
            for nb, *_ in adj[cur]:
                if nb not in comp:
                    stack.append(nb)
        remaining -= comp
        out.append(sorted(comp))
    return out


def resolve_placements(ledger: "MasterParametricLedger") -> dict[str, "Transform"]:
    """`{instance_id: world Transform}` for every instance reached by a connection. An instance with NO
    connection is absent (the caller's existing auto-layout handles it). Within a connected component the
    datum is an instance carrying an explicit `transform` (an anchor), else the ledger root if present,
    else the lowest id — and it keeps its own transform (or identity). Others are mated to it, BFS,
    first-reached-wins (a second connection into an already-placed part is ignored here and surfaced by
    `connection_issues`)."""
    from packages.ledger.schema import Transform

    adj = _adjacency(ledger)
    placed: dict[str, Transform] = {}

    # component discovery/ordering is `_connected_components`'s job (shared with `unanchored_components`);
    # this loop keeps only what's unique to placement: datum selection + mate-propagation BFS per component.
    for comp_list in _connected_components(adj):
        comp = set(comp_list)
        # choose a datum for this component: an anchored (explicit-transform) instance, else root, else min id
        anchored = [i for i in comp if ledger.instances[i].transform is not None]
        if anchored:
            datum = min(anchored)
        elif ledger.root_id in comp:
            datum = ledger.root_id
        else:
            datum = min(comp)
        placed[datum] = ledger.instances[datum].transform or _identity_transform()

        # BFS out from the datum, mating each newly-reached neighbor
        queue = [datum]
        seen = {datum}
        while queue:
            p = queue.pop(0)
            p_world = placed[p]
            for (nb, my_iface, nb_iface, gap) in adj[p]:
                if nb in seen:
                    continue
                seen.add(nb)
                # 2026-08-04 fix: a kind="mesh" pair (gear-gear) must NOT be coincidence-mated like an
                # ordinary mount/containment/port pair -- that would place both gear centers on top of
                # each other (center_distance=0), silently wrong rather than raising an error. Reuses
                # resolve_mesh_mate's own verified radius_a+radius_b/world-+X arithmetic (see that
                # function's docstring for the v1 same-Z-axis-only scope limit) rather than duplicating
                # it; falls through to the ordinary translation mate for every other kind pair, which is
                # untouched below.
                p_spec, p_frame_local = _mesh_interface(ledger, p, my_iface)
                nb_spec, nb_frame_local = _mesh_interface(ledger, nb, nb_iface)
                if p_spec.kind == "mesh" and nb_spec.kind == "mesh" \
                        and p_frame_local.radius is not None and nb_frame_local.radius is not None:
                    center_distance = p_frame_local.radius + nb_frame_local.radius
                    p_frame = _apply_transform_to_frame(p_world, p_frame_local)
                    tx = p_frame.origin[0] + center_distance - nb_frame_local.origin[0]
                    ty = p_frame.origin[1] - nb_frame_local.origin[1]
                    tz = p_frame.origin[2] - nb_frame_local.origin[2]
                else:
                    p_frame = _apply_transform_to_frame(p_world, p_frame_local)
                    nb_frame = nb_frame_local
                    # v1: pure translation (rotation-free). Push apart by gap along p's outward normal.
                    tx = p_frame.origin[0] + gap * p_frame.normal[0] - nb_frame.origin[0]
                    ty = p_frame.origin[1] + gap * p_frame.normal[1] - nb_frame.origin[1]
                    tz = p_frame.origin[2] + gap * p_frame.normal[2] - nb_frame.origin[2]
                placed[nb] = Transform(x_mm=tx, y_mm=ty, z_mm=tz)
                queue.append(nb)

    return placed


def unanchored_components(ledger: "MasterParametricLedger") -> list[list[str]]:
    """Every connected component of the connection graph that has NO anchored (explicit-`transform`)
    member, as a list of (sorted) member-id lists, ordered by each component's own minimum id --
    shares `_connected_components`'s discovery/ordering with `resolve_placements` (see that helper's
    docstring), so the two can never partition the same connection graph differently.

    2026-08-06 (gearbox-housing-generation initiative, Phase 1): `resolve_placements` above seeds a
    component with no anchored member at `_identity_transform()` (world origin) purely for lack of one
    -- fine for exactly ONE such component, but EVERY unanchored component seeds at that SAME shared
    origin independently, so a second one collides with the first (the confirmed bug: two unrelated
    mesh-connected gear pairs, neither anchored, land exactly on top of each other -- verified live,
    their resolved world bboxes come out literally identical). `assembly.py::instance_world_offsets`
    uses this list to give each such component its own auto-layout slot -- exactly like an ordinary
    unconnected instance gets one via its own lane-cursor mechanism today, just keyed by CONNECTED
    COMPONENT instead of single instance id.

    A component WITH an anchored member is deliberately EXCLUDED here -- `resolve_placements` already
    seeds it at that anchor's own explicit transform, which is authoritative and must not be
    second-guessed by auto-layout (unchanged from today's behavior; see that function's own
    datum-selection rule)."""
    adj = _adjacency(ledger)
    return [comp for comp in _connected_components(adj)
            if not any(ledger.instances[i].transform is not None for i in comp)]


def _world_frame(ledger, placements, instance_id: str, interface: str) -> Optional[Frame]:
    lf = _local_frame(ledger, instance_id, interface)
    t = placements.get(instance_id)
    if lf is None or t is None:
        return None
    return _apply_transform_to_frame(t, lf)


def world_frame_for_interface(
    ledger: "MasterParametricLedger", instance_id: str, interface: str,
) -> Optional[Frame]:
    """Any instance's declared interface, resolved to its WORLD frame (2026-07-22) -- unlike
    `_world_frame` above (which only resolves an instance already reached by `resolve_placements`'s
    connection graph), this works for EVERY instance regardless of whether it's mate-solver-placed,
    auto-laid-out, or explicitly transformed. Combines `assembly.instance_world_offsets`'s
    translation (which already handles all three placement paths uniformly, returning one
    world (x,y,z) per instance) with the instance's own `Transform.rx/ry/rz_deg` rotation -- the
    SAME two-piece combination `validate.py::_placed` and `assembly.render_assembly` already use to
    place real geometry, so this stays consistent with how the rest of the system interprets
    "where an instance actually sits" rather than inventing a second convention.

    For the "keepout" self-check (validate.py), which needs a world-space clearance zone around an
    interface no matter how that instance got positioned."""
    from packages.ledger.schema import Transform
    from packages.subsystems.assembly import instance_world_offsets

    lf = _local_frame(ledger, instance_id, interface)
    if lf is None:
        return None
    inst = ledger.instances.get(instance_id)
    if inst is None:
        return None
    ox, oy, oz = instance_world_offsets(ledger).get(instance_id, (0.0, 0.0, 0.0))
    rx = ry = rz = 0.0
    if inst.transform is not None:
        rx, ry, rz = inst.transform.rx_deg, inst.transform.ry_deg, inst.transform.rz_deg
    t = Transform(x_mm=ox, y_mm=oy, z_mm=oz, rx_deg=rx, ry_deg=ry, rz_deg=rz)
    return _apply_transform_to_frame(t, lf)


def connection_issues(ledger: "MasterParametricLedger", instance_id: str | None = None) -> list[str]:
    """Human-readable problems with the connection graph, for the self-check:
    - DANGLING: an endpoint whose instance or interface doesn't exist.
    - ROTATION-NEEDED: a mate whose normals aren't anti-parallel (the v1 solver only auto-places
      rotation-free mates — declare a transform, or wait for Phase 1b).
    - UNSATISFIED (over-constraint): a connection whose two mate points DON'T actually coincide in the
      final placement — i.e. the part was positioned by a DIFFERENT connection and this one is left
      violated. This is the "part mated by two conflicting connections" case: v1 places
      first-reached-wins and this check reports the loser instead of silently ignoring it (per
      ENGINEERING_GRAPH_PLAN.md P1.6 — report the conflict, don't attempt a full constraint solver).
    Empty list = the graph is clean.

    `instance_id` (default None -> every connection, the pre-existing/self-check-tab behavior)
    restricts the per-connection checks to connections where `instance_id` is one of the two endpoints,
    and the multiple-anchors check to whichever connected component `instance_id` actually belongs to.
    Pass it whenever the caller means ONE specific part (the export/signoff gate) — omitting it here is
    what let an unrelated part's broken connection elsewhere in the file block a fully-grounded,
    unrelated part's export (foundations-audit H3, 2026-07-21)."""
    issues: list[str] = []
    for c in ledger.connections:
        if instance_id is not None and instance_id not in (c.a.instance_id, c.b.instance_id):
            continue
        # a part cannot mate to itself
        if c.a.instance_id == c.b.instance_id:
            issues.append(f"connection {c.id}: both endpoints are the same instance "
                          f"'{c.a.instance_id}' — a part cannot connect to itself")
        for ref, label in ((c.a, "a"), (c.b, "b")):
            if ref.instance_id not in ledger.instances:
                issues.append(f"connection {c.id}: endpoint {label} references missing instance '{ref.instance_id}'")
            elif _local_frame(ledger, ref.instance_id, ref.interface) is None:
                issues.append(
                    f"connection {c.id}: endpoint {label} references interface '{ref.interface}' "
                    f"which '{ref.instance_id}' ({ledger.instances[ref.instance_id].subsystem_type}) "
                    f"does not declare")

    # WORLD-frame checks (need the resolved placements). The rotation-needed and unsatisfied guards
    # MUST use world frames, not local ones: a datum carrying a rotation makes a locally-anti-parallel
    # mate need a world rotation the v1 pure-translation solver can't do — checking LOCAL normals would
    # miss exactly that case and return a clean self-check on wrong geometry (2026-07-19 adversarial
    # review, HIGH). v1 still only TRANSLATES; this makes the guard honest about when that's not enough.
    placements = resolve_placements(ledger)
    for c in ledger.connections:
        if instance_id is not None and instance_id not in (c.a.instance_id, c.b.instance_id):
            continue
        wa = _world_frame(ledger, placements, c.a.instance_id, c.a.interface)
        wb = _world_frame(ledger, placements, c.b.instance_id, c.b.interface)
        if wa is None or wb is None:
            continue  # unplaced (no-connection/auto-layout) or dangling — already handled above
        # 2026-08-04 fix: a kind="mesh" pair (gear-gear) is NOT a touching-face mount mate — its
        # validity criteria are the OPPOSITE shape (found live: a correctly mesh-mated gear pair was
        # unconditionally flagged "need a rotation" + "do not meet", because the checks below assume
        # every connection is a coincident/anti-parallel mount mate). Two meshing gears' rotation axes
        # point the SAME direction (parallel normals, not anti-parallel), and their centers sit
        # `radius_a + radius_b` apart (not `gap_mm`/coincident) — see resolve_mesh_mate's own math,
        # which this mirrors so a correctly-solved mesh never gets flagged as broken.
        looked_up_a = _mesh_interface(ledger, c.a.instance_id, c.a.interface)
        looked_up_b = _mesh_interface(ledger, c.b.instance_id, c.b.interface)
        is_mesh_pair = (looked_up_a is not None and looked_up_b is not None
                        and looked_up_a[0].kind == "mesh" and looked_up_b[0].kind == "mesh")
        if is_mesh_pair:
            frame_a_local, frame_b_local = looked_up_a[1], looked_up_b[1]
            parallel_dot = (wa.normal[0] * wb.normal[0] + wa.normal[1] * wb.normal[1]
                            + wa.normal[2] * wb.normal[2])
            if parallel_dot < 1.0 - _ANTIPARALLEL_TOL:
                issues.append(
                    f"connection {c.id}: {c.a.instance_id}.{c.a.interface} and {c.b.instance_id}."
                    f"{c.b.interface} need a rotation to mesh (their world rotation axes aren't "
                    f"parallel — v1 only supports same-Z-axis meshing, see resolve_mesh_mate's own "
                    f"docstring) — give one side an explicit transform to align the axes")
            elif frame_a_local.radius is not None and frame_b_local.radius is not None:
                expected = frame_a_local.radius + frame_b_local.radius
                d = math.dist(wa.origin, wb.origin)
                if abs(d - expected) > 0.05:
                    issues.append(
                        f"connection {c.id}: {c.a.instance_id}.{c.a.interface} and {c.b.instance_id}."
                        f"{c.b.interface} are {d:.1f} mm apart, expected {expected:.1f} mm "
                        f"(radius_a + radius_b) — the part was placed by another connection, so this "
                        f"mesh is over-constrained/unsatisfied. Remove the conflicting connection or "
                        f"make the two mates consistent.")
            continue  # mesh pair fully checked above — skip the mount-mate checks below
        # rotation-needed: WORLD normals must be anti-parallel for a rotation-free mate
        dot = -(wa.normal[0] * wb.normal[0] + wa.normal[1] * wb.normal[1] + wa.normal[2] * wb.normal[2])
        if dot < 1.0 - _ANTIPARALLEL_TOL:
            issues.append(
                f"connection {c.id}: {c.a.instance_id}.{c.a.interface} and {c.b.instance_id}."
                f"{c.b.interface} need a rotation to mate (their world normals aren't anti-parallel — "
                f"often because a mated part carries its own rotation) — the v1 solver only auto-places "
                f"rotation-free mates; give one side an explicit transform (Phase 1b will auto-solve this)")
        # unsatisfied / over-constraint: a satisfied mate sits exactly gap_mm apart along the normal
        d = math.dist(wa.origin, wb.origin)
        if abs(d - c.gap_mm) > 0.05:
            issues.append(
                f"connection {c.id}: {c.a.instance_id}.{c.a.interface} and {c.b.instance_id}."
                f"{c.b.interface} do not meet ({d:.1f} mm apart, expected {c.gap_mm:.1f}) — the part "
                f"was placed by another connection, so this one is over-constrained/unsatisfied. Remove "
                f"the conflicting connection or make the two mates consistent.")

    # multiple anchors: v1 keeps ONE anchored (explicit-transform) instance per connected component as
    # the datum and MATES the rest — so a second anchor's explicit transform is silently overridden.
    # Flag it (the user set two fixed positions the solver can't both honor).
    adj = _adjacency(ledger)
    seen: set[str] = set()
    for start in adj:
        if start in seen or not adj[start]:
            continue
        comp: set[str] = set()
        stack = [start]
        while stack:
            cur = stack.pop()
            if cur in comp:
                continue
            comp.add(cur)
            for nb, *_ in adj[cur]:
                if nb not in comp:
                    stack.append(nb)
        seen |= comp
        if instance_id is not None and instance_id not in comp:
            continue  # v1 resolves one whole connected component together (one anchor as the datum,
            # the rest mated relative to it) -- an anchor conflict anywhere in `instance_id`'s OWN
            # component genuinely affects its placement, but a conflict in a totally separate,
            # unconnected component does not.
        anchored = sorted(i for i in comp if ledger.instances[i].transform is not None)
        if len(anchored) > 1:
            issues.append(
                f"connection graph: instances {anchored} in one connected group each carry an explicit "
                f"transform, but v1 can only honor one ('{anchored[0]}') as the datum — the others are "
                f"repositioned by mating, silently discarding their set transforms. Remove the extra "
                f"anchors or split the group.")
    return issues


# ---------------------------------------------------------------------------------------------------
# Mesh-kind (gear pitch-circle) mating (2026-08-04) — a GENUINELY DIFFERENT mate math from everything
# above. Every mount/containment mate in this file works by COINCIDING two interface origins (pure
# translation, `tx/ty/tz` in `resolve_placements`'s BFS loop above — untouched by this section). Two
# gears never coincide: they mesh when their pitch circles are TANGENT, i.e. their centers sit
# `radius_a + radius_b` apart. That is a fundamentally different equation, so — per this session's
# explicit scope — it gets its OWN function rather than a new branch bolted onto `resolve_placements`.
# ---------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class MeshMateResult:
    """Outcome of solving ONE `kind="mesh"` mate — mirrors `fit.py::FitComputeResult`'s own ok/reason
    discipline: `ok=False` means refused/unknown (with a human-readable `reason`), never a fabricated
    position. `transform` (set only when `ok`) is the SECOND gear's (`b`'s) world `Transform`, computed
    relative to the FIRST gear's (`a`'s) own current placement (`a`'s instance `.transform` if it
    carries one, else identity — the same "anchored, else identity" treatment `resolve_placements`
    gives an unconnected datum; this function does not run `a` through the BFS solver above)."""

    ok: bool
    transform: Optional["Transform"] = None
    center_distance_mm: Optional[float] = None
    reason: Optional[str] = None


def _mesh_interface(ledger: "MasterParametricLedger", instance_id: str, interface: str
                     ) -> Optional[tuple[InterfaceSpec, Frame]]:
    """Look up ONE declared interface's full `InterfaceSpec` (not just its resolved `Frame`, unlike
    `_local_frame` above) — `resolve_mesh_mate` must check `InterfaceSpec.kind` BEFORE trusting any
    geometry (treating a "mount" frame's coordinates as if they were a "mesh" pitch point would be a
    silent-wrong-answer risk, not just a style mismatch), so it needs the spec, not only the frame.
    A fresh, separate lookup — deliberately NOT a refactor of `_local_frame` (existing mate-solving
    logic in this file is left untouched, per this session's scope)."""
    inst = ledger.instances.get(instance_id)
    if inst is None:
        return None
    try:
        model = get_subsystem_model(inst.subsystem_type)
    except KeyError:
        return None
    spec = next((s for s in model.interfaces if s.name == interface), None)
    if spec is None:
        return None
    return spec, spec.frame(resolve_namespace(model, ledger, instance_id))


def resolve_mesh_mate(
    ledger: "MasterParametricLedger", a: "InterfaceRef", b: "InterfaceRef",
) -> MeshMateResult:
    """Solve a parallel-axis GEAR MESH mate: position `b`'s gear center `center_distance_mm =
    radius_a + radius_b` away from `a`'s gear center, in the plane PERPENDICULAR TO their shared Z
    axis (both gears' rotation axes are assumed parallel and Z-up — see the v1 scope limit below) —
    i.e. `b`'s center lands at the same world Z as `a`'s, offset only in X/Y. Refuses outright (never
    coerces) unless BOTH `a` and `b` name a real, declared `kind="mesh"` interface (built via
    `base.py::cylinder_axis_mesh_interface`) whose `Frame.radius` is set — the same never-coerce-on-a-
    kind-mismatch discipline `fit.py::compute_fit` already uses for its own host/connector kind check.

    v1 SCOPE LIMIT (honest, matches `cylinder_axis_mesh_interface`'s own docstring): the second gear is
    placed a fixed `center_distance_mm` along WORLD +X from the first — there is no direction/angle
    parameter yet, so this only ever produces a mesh along the world X axis. An arbitrary 3D mesh axis
    (a bevel or worm gear meshing at an angle) is NOT modeled at all; this function only ever reasons
    about a shared, world-Z-up axis pair. Do not reuse this for a non-parallel-axis mesh — it would
    silently produce a wrong position for that case rather than raising an error."""
    from packages.ledger.schema import Transform

    looked_up_a = _mesh_interface(ledger, a.instance_id, a.interface)
    if looked_up_a is None:
        return MeshMateResult(ok=False, reason=(
            f"{a.instance_id}.{a.interface}: instance or interface does not exist"))
    looked_up_b = _mesh_interface(ledger, b.instance_id, b.interface)
    if looked_up_b is None:
        return MeshMateResult(ok=False, reason=(
            f"{b.instance_id}.{b.interface}: instance or interface does not exist"))
    iface_a, frame_a = looked_up_a
    iface_b, frame_b = looked_up_b

    if iface_a.kind != "mesh" or iface_b.kind != "mesh":
        return MeshMateResult(ok=False, reason=(
            f"mesh mate requires both interfaces to be kind='mesh' — got "
            f"{a.instance_id}.{a.interface}={iface_a.kind!r}, {b.instance_id}.{b.interface}="
            f"{iface_b.kind!r} (never coerced: a non-mesh interface uses different mate math and "
            f"would silently place the part wrong if treated as a gear mesh)"))
    if frame_a.radius is None or frame_b.radius is None:
        return MeshMateResult(ok=False, reason=(
            f"mesh mate requires both interfaces to declare a pitch radius — "
            f"{a.instance_id}.{a.interface}.radius={frame_a.radius!r}, "
            f"{b.instance_id}.{b.interface}.radius={frame_b.radius!r}"))

    center_distance = frame_a.radius + frame_b.radius
    a_transform = ledger.instances[a.instance_id].transform or _identity_transform()
    a_world = _apply_transform_to_frame(a_transform, frame_a)
    target = (a_world.origin[0] + center_distance, a_world.origin[1], a_world.origin[2])
    b_transform = Transform(
        x_mm=target[0] - frame_b.origin[0],
        y_mm=target[1] - frame_b.origin[1],
        z_mm=target[2] - frame_b.origin[2],
    )
    return MeshMateResult(ok=True, transform=b_transform, center_distance_mm=center_distance)

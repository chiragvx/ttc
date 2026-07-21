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
from typing import TYPE_CHECKING, Optional

from packages.subsystems import get_subsystem_model
from packages.subsystems.base import Frame, resolve_namespace

if TYPE_CHECKING:
    from packages.ledger.schema import MasterParametricLedger, Transform

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


def resolve_placements(ledger: "MasterParametricLedger") -> dict[str, "Transform"]:
    """`{instance_id: world Transform}` for every instance reached by a connection. An instance with NO
    connection is absent (the caller's existing auto-layout handles it). Within a connected component the
    datum is an instance carrying an explicit `transform` (an anchor), else the ledger root if present,
    else the lowest id — and it keeps its own transform (or identity). Others are mated to it, BFS,
    first-reached-wins (a second connection into an already-placed part is ignored here and surfaced by
    `connection_issues`)."""
    from packages.ledger.schema import Transform

    adj = _adjacency(ledger)
    connected = {iid for iid, nbrs in adj.items() if nbrs}
    placed: dict[str, Transform] = {}

    remaining = set(connected)
    while remaining:
        # choose a datum for this component: an anchored (explicit-transform) instance, else root, else min id
        comp_seed = min(remaining)
        # gather the component via BFS on adjacency
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
                p_frame = _apply_transform_to_frame(p_world, _local_frame(ledger, p, my_iface))
                nb_frame = _local_frame(ledger, nb, nb_iface)
                # v1: pure translation (rotation-free). Push apart by gap along p's outward normal.
                tx = p_frame.origin[0] + gap * p_frame.normal[0] - nb_frame.origin[0]
                ty = p_frame.origin[1] + gap * p_frame.normal[1] - nb_frame.origin[1]
                tz = p_frame.origin[2] + gap * p_frame.normal[2] - nb_frame.origin[2]
                placed[nb] = Transform(x_mm=tx, y_mm=ty, z_mm=tz)
                queue.append(nb)

        remaining -= comp

    return placed


def _world_frame(ledger, placements, instance_id: str, interface: str) -> Optional[Frame]:
    lf = _local_frame(ledger, instance_id, interface)
    t = placements.get(instance_id)
    if lf is None or t is None:
        return None
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

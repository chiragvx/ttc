"""Event-sourced ledger — FACTS vs DERIVATIONS, hash-chained, replay as a pure fold.

The fix for existential risk #3: replay NEVER re-invokes a non-deterministic producer (LLM /
optimizer / solver). It folds over user-intent FACTS only; recomputed DERIVATIONS (generated script,
B-rep, mesh, FS verdict) are stored as first-class, content-addressed, fingerprint-stamped events and
rehydrated by hash — never recomputed.

`BaseEventLog` defines the append/replay/verify behaviour; storage is pluggable (in-memory `EventLog`
here, SQLite/Postgres `SqlEventStore` in event_store_sql.py) so both share identical semantics.
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from enum import Enum
from typing import Callable, Iterable, Optional

from pydantic import BaseModel, ConfigDict, Field

from packages.ledger.apply import apply_delta
from packages.ledger.deltas import ParameterDelta
from packages.ledger.schema import Connection, CutFeature, Instance, MasterParametricLedger, Review, ReviewState, Transform


class EventKind(str, Enum):
    GENESIS = "GENESIS"
    PARAMETER_MUTATION = "PARAMETER_MUTATION"
    REVIEW_SIGNOFF = "REVIEW_SIGNOFF"
    NL_INTENT = "NL_INTENT"
    USAGE = "USAGE"            # cost/token/compute accounting (recorded, no state change)
    DERIVATION = "DERIVATION"
    INSTANCE_ADDED = "INSTANCE_ADDED"
    INSTANCE_REMOVED = "INSTANCE_REMOVED"
    INSTANCE_MOVED = "INSTANCE_MOVED"  # reposition/reorient an ALREADY-PLACED instance
    FEATURE_OP = "FEATURE_OP"  # add/update/remove a hole/pocket/slot cut on an instance
    CONNECTION_ADDED = "CONNECTION_ADDED"      # a typed interface<->interface mate (Phase 1b)
    CONNECTION_REMOVED = "CONNECTION_REMOVED"


FACT_KINDS = {
    EventKind.GENESIS, EventKind.PARAMETER_MUTATION, EventKind.REVIEW_SIGNOFF,
    EventKind.NL_INTENT, EventKind.USAGE, EventKind.INSTANCE_ADDED, EventKind.INSTANCE_REMOVED,
    EventKind.INSTANCE_MOVED, EventKind.FEATURE_OP,
    EventKind.CONNECTION_ADDED, EventKind.CONNECTION_REMOVED,
}

# Facts that change the actual geometry/design — a prior ENGINEER_REVIEWED sign-off must not survive
# one of these (Review's own docstring: "Geometry-class changes start AI_PROPOSED"). Only ever
# appended when `outcome.changed` was True (packages/transport/app.py), so every one of these really
# did change something worth re-reviewing — never appended for a REJECTED/CONFLICT attempt.
GEOMETRY_CLASS_KINDS = {
    EventKind.PARAMETER_MUTATION, EventKind.INSTANCE_ADDED, EventKind.INSTANCE_REMOVED,
    EventKind.INSTANCE_MOVED, EventKind.FEATURE_OP,
    EventKind.CONNECTION_ADDED, EventKind.CONNECTION_REMOVED,
}

GENESIS_PREV = "0" * 64


def _canonical(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def compute_hash(prev_hash: str, kind: EventKind, seq: int, actor: str, ts: str, payload: dict) -> str:
    blob = f"{prev_hash}|{kind.value}|{seq}|{actor}|{ts}|{_canonical(payload)}"
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class Event(BaseModel):
    model_config = ConfigDict(extra="forbid")
    seq: int
    kind: EventKind
    actor: str
    ts: str
    payload: dict = Field(default_factory=dict)
    prev_hash: str
    hash: str

    @property
    def is_fact(self) -> bool:
        return self.kind in FACT_KINDS


def replay(
    events: Iterable[Event],
    reconcile: Optional[Callable[[MasterParametricLedger], MasterParametricLedger]] = None,
    initial: Optional[MasterParametricLedger] = None,
) -> MasterParametricLedger:
    """Reconstruct ledger state from FACTS only. Never calls an LLM/optimizer/solver.

    `reconcile` (default None -> every pre-2026-07-04 caller unaffected, pure fold, no side lookups)
    is an OPTIONAL injected callable — same style as `apply_delta`'s `domain_checks`/`cascade_rules`
    and `apply_feature_op`'s `build_part` — applied after EVERY fact folds, not just once at the end.
    This package still imports no OCCT/subsystem knowledge (`packages/ledger/CLAUDE.md`); the caller
    (`packages/transport/app.py::SessionState.ledger()`) supplies
    `packages.subsystems.assembly_template.reconcile_all`.

    Why per-event, not once at the end: an assembly-template child instance (e.g. a table's
    "table_1_top") is never itself an INSTANCE_ADDED fact — it only exists once `reconcile_all` runs.
    A FEATURE_OP fact targeting such a child, folded WITHOUT `reconcile` running first, hits the
    `instance_id in ledger.instances` miss below and is silently dropped (see that branch's comment)
    -- forever, since a later reconcile-once-at-the-end synthesizes a FRESH child with no memory of
    the dropped cut. Reconciling after every event closes that gap: by the time the FEATURE_OP event
    folds, the child it targets already exists (if it's an assembly-template child at all).

    `initial` (2026-07-15, default None -> every pre-existing caller unaffected — a bare `events`
    list must then include its own GENESIS) lets a caller resume folding from an ALREADY-COMPUTED
    ledger state instead of always starting from genesis. `BaseEventLog.fold()`'s snapshot cache
    uses this to fold only the events appended SINCE the last read, instead of re-folding the WHOLE
    history (with its per-event `apply_delta` deep-copy) on every single read — a demo-length session
    is fine either way, but the cost was O(events-so-far) on every read (mesh render, telemetry poll,
    param fetch, …), degrading to effectively quadratic over a long session. `events` passed
    alongside `initial` must be EXACTLY the events after whatever produced it — never re-passing a
    GENESIS event once `initial` is already set."""
    ledger: MasterParametricLedger | None = initial
    for ev in events:
        if ev.kind is EventKind.DERIVATION:
            continue  # rehydrated by hash, never recomputed
        if ev.kind is EventKind.GENESIS:
            ledger = MasterParametricLedger.model_validate(ev.payload["ledger"])
        elif ev.kind is EventKind.PARAMETER_MUTATION:
            assert ledger is not None
            ledger, _ = apply_delta(ledger, ParameterDelta.model_validate(ev.payload["delta"]))
        elif ev.kind is EventKind.REVIEW_SIGNOFF:
            assert ledger is not None
            ledger = ledger.model_copy(update={
                "review": Review(state=ReviewState.ENGINEER_REVIEWED, reviewer=ev.payload["reviewer"])})
        elif ev.kind is EventKind.INSTANCE_ADDED:
            assert ledger is not None
            instance = Instance.model_validate(ev.payload["instance"])
            new_instances = dict(ledger.instances)
            new_instances[instance.id] = instance
            update: dict = {"instances": new_instances}
            if "root_id" in ev.payload:
                update["root_id"] = ev.payload["root_id"]
            ledger = ledger.model_copy(update=update)
        elif ev.kind is EventKind.INSTANCE_REMOVED:
            assert ledger is not None
            new_instances = dict(ledger.instances)
            new_instances.pop(ev.payload["instance_id"], None)
            ledger = ledger.model_copy(update={"instances": new_instances})
        elif ev.kind is EventKind.INSTANCE_MOVED:
            assert ledger is not None
            # The fact stores the instance_id + the ALREADY-RESOLVED new Transform (exactly
            # `outcome.instance.transform` from `apply_instance_op`'s move_instance branch at the
            # time it was applied — the "preserve current rotation if omitted" resolution already
            # happened there; replay never re-derives it). A pure merge into `instance.transform`,
            # same "store the resolved fact, don't re-derive it" precedent as INSTANCE_ADDED storing
            # a fully-seeded Instance.
            instance_id = ev.payload["instance_id"]
            if instance_id in ledger.instances:  # see note below for the else-branch
                inst = ledger.instances[instance_id]
                new_transform = Transform.model_validate(ev.payload["transform"])
                new_instances = dict(ledger.instances)
                new_instances[instance_id] = inst.model_copy(update={"transform": new_transform})
                ledger = ledger.model_copy(update={"instances": new_instances})
            # else: the target instance doesn't exist in the pure-FACT ledger at this point in the
            # fold — same tolerance as FEATURE_OP's else-branch below (an assembly-template child is
            # never itself an INSTANCE_ADDED fact; it only exists once `reconcile_all` runs). Silently
            # no-op rather than raise/assert; passing `reconcile` (see this function's docstring)
            # closes the gap for the ONE caller that needs it.
        elif ev.kind is EventKind.FEATURE_OP:
            assert ledger is not None
            # The fact stores the ALREADY-RESOLVED CutFeature (op="add_feature"/"update_feature" ->
            # the feature that was added/updated; op="remove_feature" -> the one removed) — exactly
            # `FeatureOpOutcome.feature` from `packages/ledger/apply.py::apply_feature_op` at the time
            # it was applied. Replay never re-invokes a geometry builder (this package has none): it
            # is a pure merge into `instance.cut_features`, the same "store the resolved fact, don't
            # re-derive it" precedent as INSTANCE_ADDED storing a fully-seeded Instance.
            instance_id = ev.payload["instance_id"]
            if instance_id in ledger.instances:  # see note below for the else-branch
                feature = CutFeature.model_validate(ev.payload["feature"])
                inst = ledger.instances[instance_id]
                if ev.payload["op"] == "remove_feature":
                    new_features = [f for f in inst.cut_features if f.id != feature.id]
                else:
                    new_features = [feature if f.id == feature.id else f for f in inst.cut_features]
                    if not any(f.id == feature.id for f in inst.cut_features):
                        new_features.append(feature)
                new_instances = dict(ledger.instances)
                new_instances[instance_id] = inst.model_copy(update={"cut_features": new_features})
                ledger = ledger.model_copy(update={"instances": new_instances})
            # else: the target instance doesn't exist in the pure-FACT ledger at this point in the
            # fold. An assembly-template child (e.g. a table's "table_1_top") is never itself
            # persisted as an INSTANCE_ADDED fact — it is only synthesized by `reconcile_all`
            # (packages/subsystems/assembly_template.py), which lives outside this package and is
            # intentionally not reachable from here (no OCCT/subsystem imports in packages/ledger).
            # Passing `reconcile` (see this function's docstring) closes the gap for the ONE caller
            # that needs it (`SessionState.ledger()`); a bare `replay(events)` with no `reconcile` —
            # every pre-2026-07-04 caller, and any caller that genuinely doesn't need assembly-child
            # awareness — still hits this branch and silently drops the op rather than raising,
            # matching NL_INTENT/USAGE's "recorded, not always state-changing" precedent, instead of
            # crashing the whole reconstruction over one stale reference.
        elif ev.kind is EventKind.CONNECTION_ADDED:
            assert ledger is not None
            # store the resolved Connection fact (exactly ConnectionOpOutcome.connection at apply time)
            conn = Connection.model_validate(ev.payload["connection"])
            ledger = ledger.model_copy(update={
                "connections": [c for c in ledger.connections if c.id != conn.id] + [conn]})
        elif ev.kind is EventKind.CONNECTION_REMOVED:
            assert ledger is not None
            cid = ev.payload["connection_id"]
            ledger = ledger.model_copy(update={
                "connections": [c for c in ledger.connections if c.id != cid]})
        # NL_INTENT: recorded, no state change
        if (ledger is not None and ev.kind in GEOMETRY_CLASS_KINDS
                and ledger.review.state is not ReviewState.AI_PROPOSED):
            # a sign-off does not survive a subsequent geometry-class change — otherwise one
            # ENGINEER_REVIEWED from early in a session silently covers every later mutation/cut/
            # instance change forever, with no re-review ever required. This is the human-in-the-loop
            # half of the export gate; geometry_signature-driven FS staleness (derived_resolver.py) is
            # a separate mechanism that already re-blocks on most of these same changes, but review
            # state itself never reset on its own before this.
            ledger = ledger.model_copy(update={"review": Review(state=ReviewState.AI_PROPOSED, reviewer=None)})
        if ledger is not None and reconcile is not None:
            ledger = reconcile(ledger)
    if ledger is None:
        raise ValueError("no genesis event")
    return ledger


class BaseEventLog(ABC):
    """Append-only, hash-chained log. Subclasses provide storage."""

    # -- storage hooks --------------------------------------------------------
    @abstractmethod
    def _count(self) -> int: ...
    @abstractmethod
    def _last_hash(self) -> str: ...
    @abstractmethod
    def _store_event(self, ev: Event) -> None: ...
    @abstractmethod
    def _all_events(self) -> list[Event]: ...
    @abstractmethod
    def _put_artifact(self, sha256: str, content: bytes) -> None: ...
    @abstractmethod
    def _get_artifact(self, sha256: str) -> bytes | None: ...

    # -- append ---------------------------------------------------------------
    def _append(self, kind: EventKind, payload: dict, actor: str, ts: str) -> Event:
        seq = self._count()
        prev = self._last_hash() if seq else GENESIS_PREV
        h = compute_hash(prev, kind, seq, actor, ts, payload)
        ev = Event(seq=seq, kind=kind, actor=actor, ts=ts, payload=payload, prev_hash=prev, hash=h)
        self._store_event(ev)
        return ev

    def append_genesis(self, ledger: MasterParametricLedger, actor: str, ts: str) -> Event:
        if self._count():
            raise ValueError("genesis must be the first event")
        return self._append(EventKind.GENESIS, {"ledger": ledger.model_dump(mode="json")}, actor, ts)

    def append_mutation(self, delta: ParameterDelta, actor: str, ts: str) -> Event:
        return self._append(EventKind.PARAMETER_MUTATION, {"delta": delta.model_dump(mode="json")}, actor, ts)

    def append_signoff(self, reviewer: str, ts: str) -> Event:
        return self._append(EventKind.REVIEW_SIGNOFF, {"reviewer": reviewer}, reviewer, ts)

    def append_instance_added(self, instance: "Instance", actor: str, ts: str,
                              root_id: Optional[str] = None) -> Event:
        """`root_id` should be passed whenever the ADDING ledger's `root_id` is this instance's own id
        — i.e. every add, bootstrap or not, since `packages.ledger.apply.resolve_instance_parent`
        only ever changes `root_id` on a bootstrap (empty-project) add and leaves it as-is otherwise.
        Without this, `replay()` would never learn about a bootstrap's root_id (the FACT only carries
        the added Instance, not the ledger-level pointer to it) and every replay/reconstruction would
        keep the pre-genesis default root_id forever, pointing at nothing."""
        payload: dict = {"instance": instance.model_dump(mode="json")}
        if root_id is not None:
            payload["root_id"] = root_id
        return self._append(EventKind.INSTANCE_ADDED, payload, actor, ts)

    def append_instance_removed(self, instance_id: str, actor: str, ts: str) -> Event:
        return self._append(EventKind.INSTANCE_REMOVED, {"instance_id": instance_id}, actor, ts)

    def append_instance_moved(self, instance_id: str, transform: "Transform", actor: str, ts: str) -> Event:
        """The FACT counterpart to `apply_instance_op`'s move_instance OUTCOME
        (packages/ledger/apply.py): stores the instance_id + the ALREADY-RESOLVED new Transform
        (`outcome.instance.transform`, which already carries the "preserve current rotation if
        omitted" resolution) — mirrors `append_instance_removed`'s shape/style exactly."""
        return self._append(
            EventKind.INSTANCE_MOVED,
            {"instance_id": instance_id, "transform": transform.model_dump(mode="json")},
            actor, ts,
        )

    def append_feature_op(self, op: str, instance_id: str, feature: "CutFeature", actor: str, ts: str) -> Event:
        """The FACT counterpart to `apply_feature_op`'s OUTCOME (packages/ledger/apply.py): stores the
        ALREADY-RESOLVED `CutFeature` (op="remove_feature" -> the one that was removed), exactly the
        precedent `replay()`'s `EventKind.FEATURE_OP` branch above documents and expects."""
        return self._append(
            EventKind.FEATURE_OP,
            {"op": op, "instance_id": instance_id, "feature": feature.model_dump(mode="json")},
            actor, ts,
        )

    def append_connection_added(self, connection: "Connection", actor: str, ts: str) -> Event:
        """FACT counterpart to `apply_connection_op`'s add outcome — stores the resolved Connection."""
        return self._append(EventKind.CONNECTION_ADDED,
                            {"connection": connection.model_dump(mode="json")}, actor, ts)

    def append_connection_removed(self, connection_id: str, actor: str, ts: str) -> Event:
        return self._append(EventKind.CONNECTION_REMOVED, {"connection_id": connection_id}, actor, ts)

    def append_nl_intent(self, text: str, actor: str, ts: str) -> Event:
        return self._append(EventKind.NL_INTENT, {"text": text}, actor, ts)

    def append_usage(self, usage: dict, actor: str, ts: str) -> Event:
        return self._append(EventKind.USAGE, usage, actor, ts)

    def append_derivation(self, artifact_kind: str, content: bytes, fingerprint: str, actor: str, ts: str) -> Event:
        sha = hashlib.sha256(content).hexdigest()
        self._put_artifact(sha, content)
        return self._append(EventKind.DERIVATION,
                            {"artifact_kind": artifact_kind, "sha256": sha, "fingerprint": fingerprint}, actor, ts)

    def get_artifact(self, sha256: str) -> bytes | None:
        return self._get_artifact(sha256)

    # -- read -----------------------------------------------------------------
    def events(self) -> list[Event]:
        return self._all_events()

    def _events_since(self, count: int) -> list[Event]:
        """Every event after position `count` (0-indexed) — the default just slices `_all_events()`;
        `SqlEventStore`/`PgEventStore` override this with a `WHERE seq >= ?` query so a cache-hit
        `fold()` doesn't have to re-fetch (and re-deserialize) the WHOLE history from the DB just to
        grab its tail (see `fold()`'s docstring)."""
        return self._all_events()[count:]

    def fold(
        self,
        reconcile: Optional[Callable[[MasterParametricLedger], MasterParametricLedger]] = None,
    ) -> MasterParametricLedger:
        """Snapshot-cached (2026-07-15): a bare re-fold over the WHOLE event history on every single
        call — every mesh render, telemetry poll, param fetch, WS mutation response — was O(events-
        so-far) per call (each PARAMETER_MUTATION fold does a full `apply_delta` deep-copy), making a
        long session's total cost effectively quadratic in the number of reads×mutations. Caches the
        last-folded ledger + how many events produced it; a read with NO new events since then
        returns the cached ledger directly (zero replay work); a read with k NEW events folds only
        those k on top of the cache instead of refolding from genesis. `_count()` (cheap — COUNT(*)
        for SQL, len() in-memory) decides whether anything changed at all, without ever fetching the
        actual rows unless it did. Cache key includes `id(reconcile)` since folding with vs without
        `reconcile_all` produces genuinely different ledger states — a different callable invalidates
        it. Safe under this class's append-only contract: events are only ever added, never removed
        or reordered, by any caller reachable from this store's own API."""
        n = self._count()
        cache_ledger = getattr(self, "_fold_cache_ledger", None)
        cache_count = getattr(self, "_fold_cache_count", 0)
        cache_reconcile_id = getattr(self, "_fold_cache_reconcile_id", None)
        if cache_ledger is not None and cache_reconcile_id == id(reconcile) and cache_count <= n:
            new_events = self._events_since(cache_count) if cache_count < n else []
            ledger = replay(new_events, reconcile=reconcile, initial=cache_ledger) if new_events else cache_ledger
        else:
            ledger = replay(self._all_events(), reconcile=reconcile)
        self._fold_cache_ledger = ledger
        self._fold_cache_count = n
        self._fold_cache_reconcile_id = id(reconcile)
        return ledger

    def verify_chain(self) -> bool:
        prev = GENESIS_PREV
        for i, ev in enumerate(self._all_events()):
            if ev.seq != i or ev.prev_hash != prev:
                return False
            if compute_hash(prev, ev.kind, ev.seq, ev.actor, ev.ts, ev.payload) != ev.hash:
                return False
            prev = ev.hash
        return True


class EventLog(BaseEventLog):
    """In-memory event log."""

    GENESIS_PREV = GENESIS_PREV

    def __init__(self) -> None:
        self._events: list[Event] = []
        self._artifacts: dict[str, bytes] = {}

    def _count(self) -> int:
        return len(self._events)

    def _last_hash(self) -> str:
        return self._events[-1].hash

    def _store_event(self, ev: Event) -> None:
        self._events.append(ev)

    def _all_events(self) -> list[Event]:
        return list(self._events)

    def _events_since(self, count: int) -> list[Event]:
        return list(self._events[count:])  # skip re-copying the already-folded prefix

    def _put_artifact(self, sha256: str, content: bytes) -> None:
        self._artifacts[sha256] = content

    def _get_artifact(self, sha256: str) -> bytes | None:
        return self._artifacts.get(sha256)

    def clone(self) -> "EventLog":
        """Copy-on-write fork: shares prior history, then diverges independently. The fold cache is
        NOT copied — the clone gets its own on first read, cheap (whichever events it happens to
        already share with `self` will still hit "no new events" on that very first fold if nothing
        was appended in between)."""
        c = EventLog()
        c._events = list(self._events)
        c._artifacts = dict(self._artifacts)
        return c

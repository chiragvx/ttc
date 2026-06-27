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
from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field

from packages.ledger.apply import apply_delta
from packages.ledger.deltas import ParameterDelta
from packages.ledger.schema import MasterParametricLedger, Review, ReviewState


class EventKind(str, Enum):
    GENESIS = "GENESIS"
    PARAMETER_MUTATION = "PARAMETER_MUTATION"
    REVIEW_SIGNOFF = "REVIEW_SIGNOFF"
    NL_INTENT = "NL_INTENT"
    USAGE = "USAGE"            # cost/token/compute accounting (recorded, no state change)
    DERIVATION = "DERIVATION"


FACT_KINDS = {
    EventKind.GENESIS, EventKind.PARAMETER_MUTATION, EventKind.REVIEW_SIGNOFF,
    EventKind.NL_INTENT, EventKind.USAGE,
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


def replay(events: Iterable[Event]) -> MasterParametricLedger:
    """Reconstruct ledger state from FACTS only. Never calls an LLM/optimizer/solver."""
    ledger: MasterParametricLedger | None = None
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
        # NL_INTENT: recorded, no state change
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

    def fold(self) -> MasterParametricLedger:
        return replay(self._all_events())

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

    def _put_artifact(self, sha256: str, content: bytes) -> None:
        self._artifacts[sha256] = content

    def _get_artifact(self, sha256: str) -> bytes | None:
        return self._artifacts.get(sha256)

    def clone(self) -> "EventLog":
        """Copy-on-write fork: shares prior history, then diverges independently."""
        c = EventLog()
        c._events = list(self._events)
        c._artifacts = dict(self._artifacts)
        return c

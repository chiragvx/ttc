"""Verdict store — where solver verdicts live so the resolver can fill `derived` for the current geometry.

In-memory by default (single-container inline analysis + tests). The Postgres-backed store
(event_store_pg) is the shared channel in compose: the worker writes, the backend reads.
"""

from __future__ import annotations

from packages.ledger.derived_resolver import Verdict


class InMemoryVerdictStore:
    def __init__(self) -> None:
        self._v: dict[str, list[Verdict]] = {}

    def put_verdict(self, project_id: str, verdict: Verdict) -> None:
        self._v.setdefault(project_id, []).append(verdict)

    def verdicts(self, project_id: str) -> list[Verdict]:
        return list(self._v.get(project_id, []))

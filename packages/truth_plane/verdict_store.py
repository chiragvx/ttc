"""Verdict store — where solver verdicts live so the resolver can fill `derived` for the current geometry.

In-memory by default (single-container inline analysis + tests). The Postgres-backed store
(event_store_pg) is the shared channel in compose: the worker writes, the backend reads.
"""

from __future__ import annotations

from packages.ledger.derived_resolver import Verdict


class InMemoryVerdictStore:
    def __init__(self) -> None:
        self._v: dict[str, list[Verdict]] = {}
        self._opt: dict[str, dict] = {}

    def put_verdict(self, project_id: str, verdict: Verdict) -> None:
        self._v.setdefault(project_id, []).append(verdict)

    def verdicts(self, project_id: str) -> list[Verdict]:
        return list(self._v.get(project_id, []))

    # optimize-sweep result (variants + best), so the worker can hand it back to the backend
    def put_optimize(self, project_id: str, result: dict) -> None:
        self._opt[project_id] = result

    def get_optimize(self, project_id: str) -> dict | None:
        return self._opt.get(project_id)

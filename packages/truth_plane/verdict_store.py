"""Verdict store — where solver verdicts live so the resolver can fill `derived` for the current geometry.

In-memory by default (single-container inline analysis + tests). The Postgres-backed store
(event_store_pg) is the shared channel in compose: the worker writes, the backend reads.
"""

from __future__ import annotations

from dataclasses import dataclass

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


@dataclass
class JobStatus:
    status: str                    # "queued" | "running" | "done" | "failed"
    message: str | None = None


class InMemoryJobStatusStore:
    """Where a queued /analyze or /optimize job's progress lives, so a poller can tell "still
    running" apart from "failed" apart from "never even got queued" — none of which are
    distinguishable from a bare verdict lookup alone (2026-07-15 fix: the previous `publish`
    callback design couldn't cross the web-process/worker-process boundary at all in the real
    compose deployment, so a crashed job left every poller waiting forever with no signal)."""

    def __init__(self) -> None:
        self._status: dict[str, JobStatus] = {}

    def put_status(self, project_id: str, status: str, message: str | None = None) -> None:
        self._status[project_id] = JobStatus(status=status, message=message)

    def get_status(self, project_id: str) -> JobStatus | None:
        return self._status.get(project_id)

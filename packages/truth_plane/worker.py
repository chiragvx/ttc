"""Dramatiq worker entrypoint — run with `dramatiq packages.truth_plane.worker`.

Configures the shared Postgres verdict + job-status stores so the verdicts and progress this worker
computes are visible to the backend (which reads the same tables). The actor is registered via
importing `jobs`.
"""

from __future__ import annotations

from packages.ledger.event_store_pg import PgJobStatusStore, PgVerdictStore
from packages.truth_plane import jobs

jobs.configure(store=PgVerdictStore.from_env(), status_store=PgJobStatusStore.from_env())

# re-export so `dramatiq packages.truth_plane.worker` discovers the actors
run_fs_analysis = jobs.run_fs_analysis
run_optimization = jobs.run_optimization

# packages/catalog — local, Supabase-ready reference-data store

Materials, DFM/manufacturing thresholds, fastener clearance dimensions, cost rates — the domain
knowledge that used to be hand-typed Python constants scattered across `packages/ledger/bom.py` and
`packages/disciplines/*.py`, with zero external grounding (2026-07-15).

**Unlike `packages/ledger`, this package does REAL I/O** (file reads, Postgres) — it is deliberately
NOT under that package's "no I/O, pure data + validation" rule. It sits ABOVE ledger/disciplines in
the dependency graph (imports them; they never import it).

## Two storage tiers, one interface

- `SeedFileStore` (`seed_store.py`) — reads `seed_data/*.json`. The zero-infra default (no
  `DATABASE_URL` needed) — every test in this repo must keep running with no database, matching
  `EventLog`/`InMemoryVerdictStore`/`InMemoryJobStatusStore`'s established convention.
- `PgCatalogStore` (`pg_store.py`) — Postgres, its OWN `catalog` schema in the SAME database the
  ledger's event/verdict/job-status stores already use (see `docker-compose.yml`'s single `postgres`
  service) — not a second service. This is the more genuinely Supabase-style choice: Supabase itself
  is one Postgres database with multiple schemas; pointing `DATABASE_URL` at a real hosted Supabase
  instance later needs ZERO code change here, since Supabase is vanilla Postgres underneath.
- `loader.py::get_store()` picks between them exactly like `packages/transport/app.py`'s
  `_make_verdict_store()` does.

## Reseed semantics (the one thing this design must not leave ambiguous)

The seed JSON files are the **permanent source of truth**, not a one-time migration input — they
stay authoritative forever, because they're also `SeedFileStore`'s live data source.
`python -m packages.catalog.seed` (`make seed-catalog`) pushes them into Postgres: **checked-in JSON
always wins**. It upserts every seed row AND prunes any DB row whose key is no longer present in the
JSON, per table, in one pass.

Known, accepted limitation (same tone as `packages/ledger/event_store_pg.py`'s own "no migration
tool" note): a future hand-edit made directly in a hosted Supabase Studio session will be silently
reverted by the next reseed. Not solved now — a `locked BOOLEAN` column is the cheap additive fix if
it ever matters. No migration tool exists (matches this repo's only established convention:
idempotent `CREATE ... IF NOT EXISTS` DDL run at connect time) — schema changes must stay additive.

## Wiring into the live app

`packages/ledger/bom.py::set_material_db()` / `packages/disciplines/cost.py::set_machine_rate()` are
the injection seams — pure reassignment, no I/O in either of those packages themselves.
`bootstrap.py::apply_to_live_app()` is the ONE function that calls `get_store()` and applies both
overrides, each independently fault-tolerant (a catalog failure never crashes the app or blocks the
other override — the hardcoded defaults simply stand).

**Must be called from every process that reads `material()`/`MACHINE_RATE_USD_PER_HR`** — today that
is BOTH `packages/transport/app.py::create_app()` (the API process) AND
`packages/truth_plane/worker.py` (the separate Dramatiq worker process, where `analyze_geometry`'s
cost/thermal grounding actually executes). Adding a third process that touches these disciplines
needs the same call.

## What's seeded but NOT yet wired

`manufacturing.clearance_holes_mm` / `manufacturing.wall_thickness_mm` are migrated into the
database but `packages/disciplines/manufacturing.py`'s knowledge fragment still hand-types them as
prose for the LLM prompt. Templating that fragment to pull live values from the catalog is a
separate, larger scope (prompt-templating work) — deliberately deferred, not forgotten.

## Adding a new category of reference data

Materials get their own typed table (stable shape, growing rows — adding material #47 never adds a
column). Everything else uses the generic `reference_datasets`/`reference_entries` pair (unstable
shape — a brand-new category, e.g. thread pitches or surface-finish targets, is new dataset+entry
rows, never a schema migration). Add a new seed JSON file (or a new dataset inside an existing one),
run the seed script — no code change needed unless the new category needs live wiring into a
discipline (mirror `bootstrap.py`'s existing pattern for that).

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

`packages/ledger/bom.py::set_material_db()`, `packages/disciplines/cost.py::set_machine_rate()`, and
`packages/disciplines/manufacturing.py::set_dfm_reference()` are the injection seams — pure
reassignment, no I/O in any of those packages themselves. `bootstrap.py::apply_to_live_app()` is the
ONE function that calls `get_store()` and applies all three overrides, each independently
fault-tolerant (a catalog failure never crashes the app or blocks the OTHER overrides — the
hardcoded defaults simply stand).

**Must be called from every process that reads `material()` / `MACHINE_RATE_USD_PER_HR` / the
manufacturing knowledge fragment** — today that is BOTH `packages/transport/app.py::create_app()`
(the API process — the only one that builds LLM prompts, so the only one where the manufacturing
override actually matters) AND `packages/truth_plane/worker.py` (the separate Dramatiq worker
process, where `analyze_geometry`'s cost/thermal grounding executes). Calling all three from both
processes is harmless even where one is a no-op (`apply_to_live_app()`'s own contract: "call me from
every process, I'll apply whatever's actually relevant there"). Adding a third process that touches
any of these needs the same call.

`manufacturing.py`'s knowledge fragment is a CALLABLE (`DisciplineSpec.knowledge_fragment: str |
Callable[[], str]`), resolved at PROMPT-BUILD time by
`packages/disciplines/__init__.py::_fragment_text` — not a string frozen at module-import time
(which would run before `apply_to_live_app()` ever executes). The clearance-hole quick-ref and the
*advisory* recommended wall thickness are catalog-sourced this way; the *hard* min-wall floor quoted
in the same sentence deliberately is NOT — it reads `packages.ledger.apply.MIN_WALL_MM` directly (the
actually-enforced constant), so the prompt can never claim a floor that doesn't match real
export-gate enforcement.

`structures.py` (its "suggest a stiffer material" callout), `thermal.py` (its service-temp ladder and
the gate's "upgrade material" suggestion), and `cost.py` (its per-material $/kg quick-ref and
"cheapest material" callout) are all callables now, reading live `packages.ledger.bom.MATERIAL_DB`
directly — none of the three needed a separate catalog dataset, since `_apply_materials()` above
already keeps that dict itself catalog-sourced. Every discipline's knowledge fragment is catalog-live
now; none is still a string frozen at module-import time.

## Adding a new category of reference data

Materials get their own typed table (stable shape, growing rows — adding material #47 never adds a
column). Everything else uses the generic `reference_datasets`/`reference_entries` pair (unstable
shape — a brand-new category, e.g. thread pitches or surface-finish targets, is new dataset+entry
rows, never a schema migration). Add a new seed JSON file (or a new dataset inside an existing one),
run the seed script — no code change needed unless the new category needs live wiring into a
discipline (mirror `bootstrap.py`'s existing pattern for that).

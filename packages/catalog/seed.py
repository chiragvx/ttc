"""Push packages/catalog/seed_data/*.json into the Postgres catalog schema.

    python -m packages.catalog.seed      (requires DATABASE_URL)
    make seed-catalog                    (same thing)

Idempotent: safe to run repeatedly. Checked-in JSON always wins on reseed (upsert + prune any row
whose key is no longer in the JSON) — see packages/catalog/CLAUDE.md's reseed-semantics note.
"""

from __future__ import annotations

import os
import sys

from packages.catalog.seed_store import SeedFileStore


def main() -> int:
    if not os.environ.get("DATABASE_URL"):
        print("DATABASE_URL is not set — nothing to seed (this script only targets Postgres; "
              "the seed-file store is already the zero-infra default with no seeding step needed).",
              file=sys.stderr)
        return 1

    from packages.catalog.pg_store import PgCatalogStore

    seed = SeedFileStore()
    pg = PgCatalogStore.from_env()

    materials = list(seed.materials().values())
    pg.upsert_materials(materials)
    print(f"materials: upserted {len(materials)}")

    n_datasets = 0
    for key in ("manufacturing.clearance_holes_mm", "manufacturing.wall_thickness_mm",
               "cost.machine_rates_usd_per_hr"):
        dataset = seed.dataset(key)
        if dataset is None:
            continue
        pg.upsert_dataset(dataset)
        n_datasets += 1
        print(f"dataset {key!r}: upserted {len(dataset.entries)} entries")

    print(f"done — {len(materials)} materials, {n_datasets} datasets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

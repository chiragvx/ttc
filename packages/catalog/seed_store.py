"""SeedFileStore — the zero-infra DomainStore tier: reads the checked-in JSON under seed_data/.

This is the default (no DATABASE_URL needed), matching every other store in this codebase's
established convention (EventLog, InMemoryVerdictStore, InMemoryJobStatusStore all work with zero
infrastructure). The JSON files here are ALSO PgCatalogStore's seed source (packages/catalog/seed.py)
— they are the permanent source of truth, not a one-time migration input that goes stale."""

from __future__ import annotations

import json
import os

from packages.catalog.models import MaterialRecord, ReferenceDataset, ReferenceEntry

_SEED_DIR = os.path.join(os.path.dirname(__file__), "seed_data")


class SeedFileStore:
    def __init__(self, seed_dir: str | None = None) -> None:
        self._dir = seed_dir or _SEED_DIR
        self._materials: dict[str, MaterialRecord] | None = None
        self._datasets: dict[str, ReferenceDataset] | None = None

    def _load_materials(self) -> dict[str, MaterialRecord]:
        path = os.path.join(self._dir, "materials.json")
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return {m["name"]: MaterialRecord.model_validate(m) for m in data["materials"]}

    def _load_datasets(self) -> dict[str, ReferenceDataset]:
        out: dict[str, ReferenceDataset] = {}
        for fname in ("manufacturing.json", "cost.json", "electrical.json"):
            path = os.path.join(self._dir, fname)
            if not os.path.isfile(path):
                continue
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            for ds in data.get("datasets", []):
                dataset = ReferenceDataset.model_validate(ds)
                out[dataset.key] = dataset
        return out

    def materials(self) -> dict[str, MaterialRecord]:
        if self._materials is None:
            self._materials = self._load_materials()
        return dict(self._materials)

    def dataset(self, key: str) -> ReferenceDataset | None:
        if self._datasets is None:
            self._datasets = self._load_datasets()
        return self._datasets.get(key)

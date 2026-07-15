"""Typed seam for packages.catalog — the ONLY things crossing this package's boundary (root
CLAUDE.md's "typed seams only" rule). Deliberately does NOT import packages.ledger.bom.Material or
any other consumer's internal type — conversion to a consumer's own shape (e.g. Material) lives in
packages/catalog/bootstrap.py, keeping this package agnostic of who reads its data.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MaterialRecord(_Strict):
    name: str
    density_g_per_mm3: float
    youngs_mod_mpa: float
    poisson: float
    yield_mpa: float
    service_temp_c: float = 50.0
    cost_per_kg_usd: float = 25.0
    properties: dict = {}
    source: Optional[str] = None
    is_verified: bool = False


class ReferenceEntry(_Strict):
    entry_key: str
    value_numeric: Optional[float] = None
    value_text: Optional[str] = None
    unit: Optional[str] = None
    attributes: dict = {}
    source: Optional[str] = None
    notes: Optional[str] = None
    is_verified: bool = False


class ReferenceDataset(_Strict):
    key: str
    domain: str
    description: Optional[str] = None
    unit: Optional[str] = None
    source: Optional[str] = None
    version: Optional[str] = None
    entries: list[ReferenceEntry] = []

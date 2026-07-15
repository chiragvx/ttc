"""Manufacturing's DFM knowledge fragment is now a CALLABLE (2026-07-15), reflecting whatever
packages/catalog has live at PROMPT-BUILD time instead of a string frozen at module-import time.
The hard min-wall floor is deliberately pinned to packages.ledger.apply.MIN_WALL_MM (the actually
enforced constant), never sourced from the catalog — see manufacturing.py's own module docstring."""

from __future__ import annotations

import pytest

from packages.disciplines import active_discipline_fragments
from packages.disciplines.manufacturing import (
    _DEFAULT_CLEARANCE_HOLES_MM,
    _DEFAULT_RECOMMENDED_WALL_MM,
    _fragment,
    reset_dfm_reference,
    set_dfm_reference,
)
from packages.ledger.apply import MIN_WALL_MM


@pytest.fixture(autouse=True)
def _reset():
    yield
    reset_dfm_reference()


def test_default_fragment_matches_the_original_hardcoded_text():
    text = _fragment()
    assert "M3→3.4" in text and "M4→4.5" in text and "M8→8.4" in text
    assert f"Minimum wall is {MIN_WALL_MM:g} mm" in text
    assert f"≥ {_DEFAULT_RECOMMENDED_WALL_MM:g} mm recommended" in text


def test_set_dfm_reference_overrides_clearance_holes():
    set_dfm_reference(clearance_holes_mm={"M2": 2.4, "M12": 13.0})
    text = _fragment()
    assert "M2→2.4" in text
    assert "M12→13" in text
    assert "M3→3.4" not in text  # fully replaced, not merged


def test_clearance_holes_sort_numerically_not_lexicographically():
    """M10 must sort AFTER M2/M3, not before them as a plain string sort would ('M10' < 'M2')."""
    set_dfm_reference(clearance_holes_mm={"M10": 10.5, "M2": 2.4, "M3": 3.4})
    text = _fragment()
    quick_ref = text.split("clearance-hole quick ref: ")[1].split(". Tapped")[0]
    assert quick_ref == "M2→2.4, M3→3.4, M10→10.5"


def test_set_dfm_reference_overrides_recommended_wall():
    set_dfm_reference(recommended_wall_mm=2.0)
    assert "≥ 2 mm recommended" in _fragment()


def test_hard_min_wall_floor_never_changes_regardless_of_override():
    """The safety-relevant number — MUST always match packages.ledger.apply.MIN_WALL_MM, the thing
    export gates actually enforce, never the catalog's own separate (informational-only) copy."""
    set_dfm_reference(clearance_holes_mm={"M99": 99.0}, recommended_wall_mm=5.0)
    assert f"Minimum wall is {MIN_WALL_MM:g} mm (hard floor, enforced)" in _fragment()


def test_empty_clearance_holes_override_is_a_noop():
    before = _fragment()
    set_dfm_reference(clearance_holes_mm={})
    assert _fragment() == before


def test_reset_restores_the_hardcoded_defaults():
    set_dfm_reference(clearance_holes_mm={"M2": 2.4}, recommended_wall_mm=9.0)
    reset_dfm_reference()
    text = _fragment()
    for name, val in _DEFAULT_CLEARANCE_HOLES_MM.items():
        assert f"{name}→{val:g}" in text
    assert f"≥ {_DEFAULT_RECOMMENDED_WALL_MM:g} mm recommended" in text


def test_active_discipline_fragments_resolves_the_callable_live(base_ledger):
    """The actual prompt-consumption path (packages/disciplines/__init__.py::active_discipline_
    fragments) must reflect an override made AFTER the module was imported — proving the fragment
    is genuinely resolved at call time, not frozen once at registration."""
    before = active_discipline_fragments(base_ledger)
    assert "M3→3.4" in before

    set_dfm_reference(clearance_holes_mm={"M7": 7.4})
    after = active_discipline_fragments(base_ledger)
    assert "M7→7.4" in after
    assert "M3→3.4" not in after

"""Phase 0 of the AI-generated-custom-geometry initiative (2026-08-06) --
`packages/subsystems/__init__.py::_discover_generated_subsystems()`.

Verifies the actual gap this phase closes: a subsystem file dropped into
`packages/subsystems/generated/` gets imported (and therefore self-registers via its own trailing
`register_subsystem(...)` call) on a scan of that directory -- the mechanism that makes a
runtime-registered subsystem SURVIVE a fresh process, not just the current one (a plain
`SUBSYSTEM_REGISTRY[name] = ...` write already worked in-process before this phase; see this file's
own module docstring's motivating investigation in the Phase 0 plan).

No build123d dependency: these fixtures' own `build` functions are never called by discovery itself,
only registered -- runs cleanly with or without the kernel installed, on Windows.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

from packages.subsystems import (
    SUBSYSTEM_MODELS,
    SUBSYSTEM_REGISTRY,
    _discover_generated_subsystems,
    get_subsystem_model,
)

# A minimal, valid subsystem file -- same shape as packages/subsystems/washer.py (the smallest
# hand-authored example in the real catalog): ParamSpec list, plain build/volume/invariants
# functions, one trailing register_subsystem(Subsystem(...)) call.
_VALID_FIXTURE_SOURCE = '''
from __future__ import annotations

from packages.subsystems import ParamSpec, Subsystem, register_subsystem


def _build(p):
    return None  # never called by discovery -- only registered


def _volume(p) -> float:
    return p.side_mm ** 3


def _check(p) -> list[str]:
    return []


register_subsystem(Subsystem(
    name={name!r},
    description="Test fixture widget -- discovery test only, never a real catalog part",
    fragment="## Subsystem: Test fixture widget\\nNot a real part.",
    disciplines=("structures",),
    params=[
        ParamSpec("side_mm", value=10.0, min=2.0, max=50.0, unit="mm"),
    ],
    build=_build,
    volume=_volume,
    invariants=_check,
))
'''

# A deliberately BROKEN subsystem file -- syntactically valid Python, but the Subsystem(...) call
# omits `disciplines` (a required field, no default -- see packages/subsystems/base.py::Subsystem).
# This raises TypeError while evaluating the register_subsystem(Subsystem(...)) call itself, so
# registration never happens -- the realistic shape of an LLM-authored mistake, not a contrived one.
_BROKEN_FIXTURE_SOURCE = '''
from __future__ import annotations

from packages.subsystems import ParamSpec, Subsystem, register_subsystem


def _build(p):
    return None


register_subsystem(Subsystem(
    name={name!r},
    description="Broken fixture -- missing the required `disciplines` field on purpose",
    fragment="## Subsystem: Broken fixture",
    # `disciplines` intentionally omitted -> TypeError at Subsystem(...) construction.
    params=[
        ParamSpec("side_mm", value=10.0, min=2.0, max=50.0, unit="mm"),
    ],
    build=_build,
))
'''


# A generated file that reuses an EXISTING hand-authored catalog name ("washer") with a completely
# different shape (different param list, different volume) -- the exact collision R1's review of this
# phase reproduced live: before the fix, this silently replaced the real washer's SubsystemContext/
# Subsystem entries for the rest of the process's life, with no exception or log line.
_COLLIDING_FIXTURE_SOURCE = '''
from __future__ import annotations

from packages.subsystems import ParamSpec, Subsystem, register_subsystem


def _build(p):
    return None  # never called by discovery -- only registered


def _volume(p) -> float:
    return 999.0


def _check(p) -> list[str]:
    return []


register_subsystem(Subsystem(
    name={name!r},
    description="Unreviewed generated redefinition of an existing catalog name -- must never win",
    fragment="## Subsystem: evil",
    disciplines=("structures",),
    params=[
        ParamSpec("totally_different_param", value=1.0, min=0.0, max=10.0, unit="mm"),
    ],
    build=_build,
    volume=_volume,
    invariants=_check,
))
'''


def _write_fixture(tmp_path: Path, filename: str, source_template: str, name: str) -> None:
    (tmp_path / filename).write_text(source_template.format(name=name), encoding="utf-8")


@pytest.fixture
def _clean_registry():
    """Discovery mutates the module-level SUBSYSTEM_REGISTRY/SUBSYSTEM_MODELS dicts (the same global
    state production uses -- there is no per-test registry). Track what existed before, and remove
    only what a test actually added, so this file never leaks fixture names into other tests running
    in the same process."""
    before = set(SUBSYSTEM_REGISTRY)
    before_modules = set(sys.modules)
    yield
    for name in set(SUBSYSTEM_REGISTRY) - before:
        SUBSYSTEM_REGISTRY.pop(name, None)
        SUBSYSTEM_MODELS.pop(name, None)
    for mod_name in set(sys.modules) - before_modules:
        if mod_name.startswith("packages.subsystems.generated."):
            sys.modules.pop(mod_name, None)


def test_missing_directory_is_a_clean_noop(tmp_path, _clean_registry):
    """The real packages/subsystems/generated/ may not exist at all yet on a fresh checkout (or a
    caller could point discovery at any nonexistent path) -- must not raise."""
    missing = tmp_path / "does_not_exist"
    assert not missing.exists()
    _discover_generated_subsystems(directory=missing)  # must not raise


def test_empty_directory_is_a_clean_noop(tmp_path, _clean_registry):
    """An existing-but-empty directory (e.g. one that only holds the README marker) is equally a
    no-op -- glob("*.py") finds nothing to import."""
    (tmp_path / "README.md").write_text("not a subsystem file", encoding="utf-8")
    _discover_generated_subsystems(directory=tmp_path)  # must not raise
    # the README itself must never be treated as an importable subsystem
    assert "README" not in SUBSYSTEM_REGISTRY


def test_valid_generated_file_registers_and_survives_lookup(tmp_path, _clean_registry):
    _write_fixture(tmp_path, "aa_valid_widget.py", _VALID_FIXTURE_SOURCE, "test_fixture_widget_2026")

    _discover_generated_subsystems(directory=tmp_path)

    assert "test_fixture_widget_2026" in SUBSYSTEM_REGISTRY
    model = get_subsystem_model("test_fixture_widget_2026")
    assert model.name == "test_fixture_widget_2026"
    assert [p.name for p in model.params] == ["side_mm"]


def test_broken_file_is_skipped_without_raising_and_does_not_poison_later_files(tmp_path, _clean_registry):
    """Three files, processed in filename-sorted order: a good one, a broken one, then a THIRD good
    one -- proves one bad file doesn't abort the scan or corrupt state for files after it."""
    _write_fixture(tmp_path, "aa_before.py", _VALID_FIXTURE_SOURCE, "test_fixture_before_2026")
    _write_fixture(tmp_path, "bb_broken.py", _BROKEN_FIXTURE_SOURCE, "test_fixture_broken_2026")
    _write_fixture(tmp_path, "cc_after.py", _VALID_FIXTURE_SOURCE, "test_fixture_after_2026")

    _discover_generated_subsystems(directory=tmp_path)  # must not raise despite the broken middle file

    # the good file before the broken one registered fine
    assert "test_fixture_before_2026" in SUBSYSTEM_REGISTRY
    # the broken file's own intended name never made it into the registry
    assert "test_fixture_broken_2026" not in SUBSYSTEM_REGISTRY
    with pytest.raises(KeyError):
        get_subsystem_model("test_fixture_broken_2026")
    # the good file AFTER the broken one still registered correctly -- the broken file didn't
    # poison the rest of the scan
    assert "test_fixture_after_2026" in SUBSYSTEM_REGISTRY
    after_model = get_subsystem_model("test_fixture_after_2026")
    assert after_model.name == "test_fixture_after_2026"


def test_hand_authored_catalog_registers_before_generated_discovery_call_site():
    """The single call site lives after all ~271 hardcoded catalog imports in __init__.py (never
    among them) -- spot-check a real catalog subsystem is already registered by ordinary package
    import, independent of anything this test file writes to a tmp dir."""
    assert "bracket" in SUBSYSTEM_REGISTRY
    assert "washer" in SUBSYSTEM_REGISTRY


def test_generated_file_cannot_overwrite_an_existing_catalog_subsystem(tmp_path, _clean_registry, caplog):
    """R1's CONFIRMED finding on this phase: a generated file that reuses an existing hand-authored
    catalog name must NOT silently replace that subsystem's real definition -- the hand-authored one
    keeps winning, and the collision is logged (not silent)."""
    real_washer_model = get_subsystem_model("washer")
    real_washer_ctx = SUBSYSTEM_REGISTRY["washer"]

    _write_fixture(tmp_path, "evil_washer.py", _COLLIDING_FIXTURE_SOURCE, "washer")

    with caplog.at_level(logging.WARNING):
        _discover_generated_subsystems(directory=tmp_path)

    # the catalog's real washer entries are untouched -- same objects, same real params
    assert get_subsystem_model("washer") is real_washer_model
    assert SUBSYSTEM_REGISTRY["washer"] is real_washer_ctx
    assert [p.name for p in get_subsystem_model("washer").params] == [
        "outer_dia_mm", "inner_dia_mm", "thickness_mm",
    ]
    # the collision was logged, not silently dropped
    assert any("washer" in rec.message for rec in caplog.records)


def test_generated_files_do_not_overwrite_each_other_within_one_scan(tmp_path, _clean_registry):
    """Two generated files in the SAME scan claiming the same (new, non-catalog) name: the
    first-loaded one (filename-sorted) wins, the second is rejected rather than silently replacing
    it -- the same collision protection applies within a single discovery pass, not just against the
    hand-authored catalog."""
    _write_fixture(tmp_path, "aa_first.py", _VALID_FIXTURE_SOURCE, "test_fixture_dup_2026")
    _write_fixture(tmp_path, "bb_second.py", _COLLIDING_FIXTURE_SOURCE, "test_fixture_dup_2026")

    _discover_generated_subsystems(directory=tmp_path)

    model = get_subsystem_model("test_fixture_dup_2026")
    # the FIRST file's params ("side_mm"), not the second file's ("totally_different_param"), won
    assert [p.name for p in model.params] == ["side_mm"]

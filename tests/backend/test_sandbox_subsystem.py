"""Sandboxed subsystem build+validate: executes untrusted, LLM-generated build123d code out-of-process
and classifies the outcome into one of 5 typed statuses (OK/BUILD_ERROR/TIMEOUT_KILLED/
MALFORMED_OUTPUT/DEGENERATE) — Phase 1 of the AI-generated-custom-geometry initiative (see
C:\\Users\\Chirag\\.claude\\plans\\spicy-exploring-cupcake.md).

Lives under tests/backend/, NOT tests/truth_plane/ — confirmed by directory listing before writing this
file: tests/truth_plane/ does not exist anywhere in this repo, and the existing sandbox.py tests
(tests/backend/test_sandbox.py, run alongside this file below) already establish tests/backend/ as
where truth_plane's sandbox-layer tests live.

This is the FIRST real production caller of `run_sandboxed` (packages/truth_plane/sandbox.py) — confirmed
by repo-wide grep before writing this: previously only test_sandbox.py itself called it.

HONEST CONTAINMENT SCOPE (already documented in sandbox.py's own module docstring — not something this
phase fixes): on Windows (this dev box) only the host-side wall-clock SIGKILL is real containment. The
process-group isolation (`os.setsid` + `killpg`) and the `RLIMIT_AS` memory cap are both POSIX-gated
no-ops here — timeout falls back to a plain, single-process `proc.kill()`. Real memory/process-tree
containment only exists on Linux, the sandbox's actual deployment target.

KERNEL-MARKER SCOPE (see sandbox_subsystem.py's own module docstring for the full "why"): build123d is
never pre-imported by the harness — candidate `build_code` imports it itself, exactly like every real
subsystem's own `_build(p)` already does. That means the BUILD_ERROR and TIMEOUT_KILLED tests below
genuinely never touch build123d and run on any machine, unmarked; only the tests that build real
geometry (OK, DEGENERATE, the optional garbage-stdout case) carry `@pytest.mark.needs_kernel` +
`@pytest.mark.skipif(not HAS_B123D, ...)` — this repo's real existing convention, matched from
tests/subsystems/test_spur_gear.py (a module-level `HAS_*`/`find_spec` guard + per-test skipif; the
`needs_kernel` marker itself is pre-registered in pyproject.toml and deselected in CI via
`pytest -m "not needs_kernel and not live"`, .github/workflows/ci.yml — it does not by itself skip
anything locally). This Windows dev box DOES have build123d pip-installed (confirmed live this session:
`python -c "import build123d; print(build123d.__version__)"` -> 0.10.0), so HAS_B123D is True here and
these tests actually execute for real, not just skip cleanly.
"""

from __future__ import annotations

import importlib.util
import time

import pytest

from packages.truth_plane import sandbox_subsystem as sandbox_subsystem_module
from packages.truth_plane.sandbox import SandboxResult
from packages.truth_plane.sandbox_subsystem import sandbox_build_and_validate

HAS_B123D = importlib.util.find_spec("build123d") is not None

_NO_PARAMS: list[dict] = []


# --- OK (needs real geometry) ------------------------------------------------------------------------

@pytest.mark.needs_kernel
@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_trivial_valid_box_resolves_ok_with_correct_volume_and_bbox():
    build_code = (
        "def build(p):\n"
        "    import build123d as bd\n"
        "    return bd.Box(10, 10, 10)\n"
    )
    result = sandbox_build_and_validate(build_code, _NO_PARAMS)
    assert result.status == "OK"
    assert result.volume_mm3 == pytest.approx(1000.0)
    (minx, miny, minz), (maxx, maxy, maxz) = result.bbox_mm
    assert (maxx - minx) == pytest.approx(10.0)
    assert (maxy - miny) == pytest.approx(10.0)
    assert (maxz - minz) == pytest.approx(10.0)


@pytest.mark.needs_kernel
@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_params_reach_build_as_namespace_attributes():
    # Proves the params -> _Namespace plumbing is real, not just defaults hard-coded in the bootstrap:
    # a box sized from p.w/p.d/p.h, not literal 10/10/10.
    build_code = (
        "def build(p):\n"
        "    import build123d as bd\n"
        "    return bd.Box(p.w, p.d, p.h)\n"
    )
    params = [
        {"name": "w", "value": 4.0, "unit": "mm"},
        {"name": "d", "value": 5.0, "unit": "mm"},
        {"name": "h", "value": 6.0, "unit": "mm"},
    ]
    result = sandbox_build_and_validate(build_code, params)
    assert result.status == "OK"
    assert result.volume_mm3 == pytest.approx(4.0 * 5.0 * 6.0)


# --- BUILD_ERROR (candidate code never touches build123d -- no kernel marker needed) ------------------

def test_raising_build_resolves_build_error_with_message():
    build_code = (
        "def build(p):\n"
        "    raise ValueError('boom')\n"
    )
    result = sandbox_build_and_validate(build_code, _NO_PARAMS)
    assert result.status == "BUILD_ERROR"
    assert "boom" in result.message


def test_missing_build_function_resolves_build_error():
    # No `build` defined at all -- the harness's own "did you define build(p)?" check, exercised
    # directly rather than only implicitly via every other test defining one.
    build_code = "x = 1 + 1\n"
    result = sandbox_build_and_validate(build_code, _NO_PARAMS)
    assert result.status == "BUILD_ERROR"
    assert "build" in result.message.lower()


# --- TIMEOUT_KILLED (candidate code never touches build123d -- no kernel marker needed; DOES take real
# wall-clock time, close to the real 8s default, per this phase's own instructions: don't shrink the
# bound just to make the test faster at the cost of a less realistic one) -----------------------------

def test_infinite_loop_is_killed_and_reported_as_timeout():
    build_code = (
        "def build(p):\n"
        "    while True:\n"
        "        pass\n"
    )
    start = time.monotonic()
    result = sandbox_build_and_validate(build_code, _NO_PARAMS)  # real 8.0s default, not shrunk
    elapsed = time.monotonic() - start
    assert result.status == "TIMEOUT_KILLED"
    assert elapsed < 24.0  # actually reaped, not hung -- same ~3x margin test_sandbox.py's own test uses
    assert elapsed > 4.0   # genuinely ran close to the deadline, not a fast short-circuit


# --- DEGENERATE (needs real geometry) ------------------------------------------------------------------

@pytest.mark.needs_kernel
@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_self_subtracted_box_resolves_degenerate():
    # bd.Box(0, 10, 10) itself RAISES inside OCCT (Standard_DomainError) rather than returning a
    # degenerate solid -- verified directly before writing this test, so it's not usable as the
    # degenerate case (it would resolve BUILD_ERROR, not DEGENERATE). Self-subtraction (a - a) is the
    # robust way to reach a genuinely-BUILT, genuinely-empty solid: volume exactly 0, every bbox axis
    # exactly 0-extent -- also verified directly.
    build_code = (
        "def build(p):\n"
        "    import build123d as bd\n"
        "    a = bd.Box(10, 10, 10)\n"
        "    b = bd.Box(10, 10, 10)\n"
        "    return a - b\n"
    )
    result = sandbox_build_and_validate(build_code, _NO_PARAMS)
    assert result.status == "DEGENERATE"
    assert result.volume_mm3 == pytest.approx(0.0)


# --- MALFORMED_OUTPUT (host-side classification, deterministic -- run_sandboxed mocked so this is a
# focused unit test of the parsing/classification logic, not a fight to provoke a genuine child crash
# from the outside; see sandbox_subsystem.py's _parse_last_result_line docstring for the one real case
# this covers: stdout that, however it got that way, never contains a shape-matching JSON line) --------

def test_unparseable_stdout_resolves_malformed_output(monkeypatch):
    fake = SandboxResult(status="OK", returncode=0, stdout="not json at all\nnor is this\n",
                          stderr="", killed=False, elapsed_s=0.01)
    monkeypatch.setattr(sandbox_subsystem_module, "run_sandboxed", lambda *a, **k: fake)
    result = sandbox_build_and_validate("def build(p):\n    pass\n", _NO_PARAMS)
    assert result.status == "MALFORMED_OUTPUT"


def test_wrong_shaped_json_on_stdout_resolves_malformed_output(monkeypatch):
    # A line that parses as JSON and even happens to have an "ok" key isn't enough -- it must match the
    # harness's own full result contract (volume_mm3 + bbox_mm when ok=true). Guards against silently
    # accepting a candidate's own coincidentally ok-shaped debug print as if it were the real result.
    fake = SandboxResult(status="OK", returncode=0, stdout='{"ok": true}\n', stderr="",
                          killed=False, elapsed_s=0.01)
    monkeypatch.setattr(sandbox_subsystem_module, "run_sandboxed", lambda *a, **k: fake)
    result = sandbox_build_and_validate("def build(p):\n    pass\n", _NO_PARAMS)
    assert result.status == "MALFORMED_OUTPUT"


# --- optional: garbage printed before a valid result line still resolves OK (needs real geometry) -----

@pytest.mark.needs_kernel
@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_garbage_printed_before_valid_result_still_resolves_ok():
    # An accidental print() inside candidate build_code -- including one that LOOKS like a harness
    # result line but is missing the required keys -- must not corrupt the single-line-JSON contract:
    # _parse_last_result_line scans from the end, and the harness's own real result line is always the
    # physically last thing printed (see its docstring for the one case this does NOT cover).
    build_code = (
        "def build(p):\n"
        "    import json\n"
        "    print('an accidental debug print from candidate code')\n"
        "    print(json.dumps({'ok': True}))\n"  # shape-incomplete decoy -- must be skipped
        "    import build123d as bd\n"
        "    return bd.Box(4, 5, 6)\n"
    )
    result = sandbox_build_and_validate(build_code, _NO_PARAMS)
    assert result.status == "OK"
    assert result.volume_mm3 == pytest.approx(4.0 * 5.0 * 6.0)

"""Sandbox containment primitives: wall-clock SIGKILL of a spinning process, clean runs, mem limit."""

from __future__ import annotations

import os

import pytest

from packages.truth_plane.sandbox import run_sandboxed


def test_normal_code_runs_and_returns_output():
    r = run_sandboxed("print('hello from sandbox')", wall_clock_s=5.0)
    assert r.status == "OK"
    assert "hello from sandbox" in r.stdout


def test_spinning_process_is_killed_within_deadline():
    # an uninterruptible busy loop — the OCCT-degenerate-boolean analogue
    r = run_sandboxed("while True: pass", wall_clock_s=1.0)
    assert r.status == "TIMEOUT_KILLED"
    assert r.killed is True
    assert r.elapsed_s < 3.0  # actually reaped, not hung


def test_error_in_code_is_reported_not_raised():
    r = run_sandboxed("raise ValueError('boom')", wall_clock_s=5.0)
    assert r.status == "ERROR"
    assert "ValueError" in r.stderr


@pytest.mark.skipif(os.name != "posix", reason="RLIMIT_AS is POSIX-only")
def test_memory_limit_is_enforced_on_posix():
    # try to allocate ~1 GB under a 256 MB cap -> the child fails, parent stays healthy
    r = run_sandboxed("x = bytearray(1024*1024*1024)", wall_clock_s=10.0, mem_limit_mb=256)
    assert r.status == "ERROR" and not r.killed

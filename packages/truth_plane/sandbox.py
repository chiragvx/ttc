"""Sandboxed execution of generated code — the containment primitives.

The load-bearing safety primitive is a HOST-SIDE wall-clock SIGKILL: a degenerate OCCT boolean can
spin uninterruptibly (and a C++ Standard_Failure can't be caught in Python), so the only reliable
containment is to run out-of-process and kill the whole process group from the parent when it blows
the deadline. On POSIX we also apply RLIMIT_AS (address-space cap).

Scope honesty: full isolation (filesystem, an egress-deny network namespace, seccomp) requires running
this under gVisor (runsc) or a Firecracker microVM in production — that is a deployment wrapper around
exactly this out-of-process model. This module provides the kill + resource primitives that work today
and are unit-testable; it is NOT a security boundary on its own.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass


@dataclass
class SandboxResult:
    status: str           # OK | ERROR | TIMEOUT_KILLED
    returncode: int | None
    stdout: str
    stderr: str
    killed: bool
    elapsed_s: float


def run_sandboxed(code: str, *, wall_clock_s: float = 2.0, mem_limit_mb: int | None = 512) -> SandboxResult:
    """Run `code` in a fresh, isolated Python process; kill it (process group) if it exceeds the
    wall-clock deadline. Returns a typed result — never raises on a runaway child."""
    preexec = None
    if os.name == "posix":
        def preexec():  # noqa: E306 - defined only on posix
            os.setsid()  # new session/group so we can killpg the whole subtree
            if mem_limit_mb:
                import resource
                nbytes = mem_limit_mb * 1024 * 1024
                resource.setrlimit(resource.RLIMIT_AS, (nbytes, nbytes))

    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    start = time.monotonic()
    proc = subprocess.Popen(
        [sys.executable, "-I", "-c", code],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        preexec_fn=preexec, creationflags=creationflags,
    )
    killed = False
    try:
        out, err = proc.communicate(timeout=wall_clock_s)
        status = "OK" if proc.returncode == 0 else "ERROR"
    except subprocess.TimeoutExpired:
        killed = True
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
        out, err = proc.communicate()
        status = "TIMEOUT_KILLED"
    return SandboxResult(status=status, returncode=proc.returncode, stdout=out, stderr=err,
                         killed=killed, elapsed_s=time.monotonic() - start)

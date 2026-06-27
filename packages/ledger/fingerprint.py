"""Toolchain fingerprint — the content-address stamp for determinism & replay (existential risk #3).

Pure-Python (no kernel import); reports kernel/lib versions if present, "absent" otherwise. Every
DERIVATION event is stamped with this so replay can detect a changed toolchain and refuse to silently
recompute. `scripts/toolchain_fingerprint.py` is a thin CLI over this module.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
from importlib.metadata import PackageNotFoundError, version

_KERNEL_PACKAGES = ("build123d", "cadquery-ocp", "numpy", "gmsh")


def _pkg_versions() -> dict[str, str]:
    out: dict[str, str] = {}
    for name in _KERNEL_PACKAGES:
        try:
            out[name] = version(name)
        except PackageNotFoundError:
            out[name] = "absent"
    return out


def fingerprint_inputs(portable: bool = False) -> dict:
    data: dict = {
        "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "packages": _pkg_versions(),
    }
    if not portable:
        data["platform"] = {
            "system": platform.system(),
            "machine": platform.machine(),
            "omp_num_threads": os.environ.get("OMP_NUM_THREADS", "unset"),
            "openblas_num_threads": os.environ.get("OPENBLAS_NUM_THREADS", "unset"),
        }
    return data


def fingerprint(portable: bool = False) -> str:
    blob = json.dumps(fingerprint_inputs(portable), sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()

"""Lightweight copyleft / slicer-isolation gate (Phase 0).

FAILS the build on:
  * an AGPL distribution in the PROJECT'S dependency closure — AGPL-3.0 §13's network clause can
    compel open-sourcing the whole proprietary server, so it must never be in-process;
  * any in-process import of a known slicer library in `packages/` — the slicer MUST be an
    out-of-process, file/CLI sidecar (the boundary that keeps AGPL as mere aggregation).
WARNS on GPL/LGPL (LGPL = OCCT/cadquery-ocp; fine for dynamic linking but carries a relink/notice
duty on any on-prem ship — tracked, not blocking).

Design notes:
  * Scans the project's closure (walks `requires()` from the installed project), NOT the whole
    environment. If the project isn't installed (e.g. a polluted local global env), it falls back to
    scanning all dists but DOWNGRADES AGPL to a warning — so CI (clean venv == closure) stays strict
    while a local run isn't blocked by unrelated globally-installed packages.
  * License is detected from CLASSIFIERS + the PEP 639 `License-Expression` + a SHORT `License`
    field — never by substring-scanning full license TEXT (which yields false positives like numpy).
Stdlib only. GitHub annotations (::error::/::warning::) render inline in the PR.
"""

from __future__ import annotations

import re
import sys
from importlib.metadata import PackageNotFoundError, distributions, requires
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ROOT = "grounded-text-to-cad"
SLICER_INPROC = {"libslic3r", "pyslic3r", "slic3r", "cura", "curaengine"}


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def project_closure() -> set[str] | None:
    """Set of normalized dist names in the project's dependency closure, or None if the project
    isn't installed (so the caller can fall back + downgrade severity)."""
    try:
        requires(ROOT)
    except PackageNotFoundError:
        return None
    seen: set[str] = set()
    stack = [ROOT]
    while stack:
        cur = stack.pop()
        key = _norm(cur)
        if key in seen:
            continue
        seen.add(key)
        try:
            reqs = requires(cur) or []
        except PackageNotFoundError:
            continue
        for r in reqs:
            # skip optional-extra requirements gated by an extra marker (dev tooling, etc.)
            if "extra ==" in r:
                continue
            dep = re.split(r"[<>=!~;\[ (]", r.strip(), maxsplit=1)[0]
            if dep:
                stack.append(dep)
    return seen


def _license_signals(dist) -> str:
    meta = dist.metadata
    sigs: list[str] = []
    expr = meta.get("License-Expression")
    if expr:
        sigs.append(expr.upper())
    for c in meta.get_all("Classifier", []) or []:
        if c.startswith("License ::"):
            sigs.append(c.upper())
    lic = (meta.get("License") or "").strip()
    if lic and len(lic) <= 40:  # short id only; skip full license text to avoid false positives
        sigs.append(lic.upper())
    return " | ".join(sigs)


def scan_licenses(closure: set[str] | None) -> tuple[list[str], list[str]]:
    hard, warn = [], []
    for dist in distributions():
        name = dist.metadata.get("Name", "?")
        in_scope = closure is None or _norm(name) in closure
        sigs = _license_signals(dist)
        if "AGPL" in sigs:
            if closure is not None and in_scope:
                hard.append(f"::error::AGPL in dependency closure: {name} — must be an out-of-process sidecar or removed")
            else:
                warn.append(f"::warning::AGPL present (not in project closure / closure unknown): {name}")
        elif "GPL" in sigs and in_scope:  # includes LGPL
            warn.append(f"::warning::copyleft (review): {name} [{sigs[:70]}]")
    return hard, warn


def scan_slicer_imports() -> list[str]:
    bad = []
    for path in (REPO / "packages").rglob("*.py"):
        try:
            tree_src = path.read_text(encoding="utf-8")
        except OSError:
            continue
        import ast
        try:
            tree = ast.parse(tree_src)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            mods: list[str] = []
            if isinstance(node, ast.Import):
                mods = [n.name.split(".")[0] for n in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods = [node.module.split(".")[0]]
            for m in mods:
                if m in SLICER_INPROC:
                    rel = path.relative_to(REPO).as_posix()
                    bad.append(f"::error file={rel},line={node.lineno}::in-process slicer import '{m}' — must be out-of-process")
    return bad


def main() -> int:
    closure = project_closure()
    if closure is None:
        print("note: project not installed; scanning all dists with AGPL downgraded to a warning "
              "(authoritative result requires an isolated venv / CI).")
    hard, warn = scan_licenses(closure)
    slicer = scan_slicer_imports()
    for w in warn:
        print(w)
    failures = hard + slicer
    for f in failures:
        print(f)
    if failures:
        print(f"FAIL: {len(failures)} copyleft/slicer-isolation violation(s)")
        return 1
    print("OK: no AGPL in closure, no in-process slicer imports")
    return 0


if __name__ == "__main__":
    sys.exit(main())

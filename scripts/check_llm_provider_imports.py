"""Fail the build if the Anthropic SDK is imported anywhere outside the LLMProvider seam.

This keeps the hosted-vs-air-gapped swap a config change rather than a rewrite (Phase 0 §3a #3): no
call site, log sink, or eval harness may hard-code `anthropic`. Pure-stdlib (ast) so it runs anywhere.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PKG = REPO / "packages"
ALLOWED = {"packages/agents/llm_provider.py"}
BANNED_TOP_LEVEL = {"anthropic"}


def _offences(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                if n.name.split(".")[0] in BANNED_TOP_LEVEL:
                    out.append((node.lineno, n.name))
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".")[0] in BANNED_TOP_LEVEL:
                out.append((node.lineno, node.module))
    return out


def main() -> int:
    violations: list[str] = []
    for path in PKG.rglob("*.py"):
        rel = path.relative_to(REPO).as_posix()
        if rel in ALLOWED:
            continue
        for lineno, name in _offences(path):
            violations.append(f"::error file={rel},line={lineno}::imports '{name}' outside the LLMProvider seam")
    if violations:
        print("\n".join(violations))
        print(f"FAIL: {len(violations)} Anthropic-SDK import(s) outside packages/agents/llm_provider.py")
        return 1
    print("OK: no Anthropic SDK imports outside the LLMProvider seam")
    return 0


if __name__ == "__main__":
    sys.exit(main())

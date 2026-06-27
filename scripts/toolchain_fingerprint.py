"""Thin CLI over packages.ledger.fingerprint. Run: python scripts/toolchain_fingerprint.py [--portable] [--json]"""

from __future__ import annotations

import argparse
import json
import sys

from packages.ledger.fingerprint import fingerprint, fingerprint_inputs


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Compute the toolchain fingerprint.")
    ap.add_argument("--portable", action="store_true", help="versions only, exclude OS/arch/threads")
    ap.add_argument("--json", action="store_true", help="emit the full input dict + hash as JSON")
    args = ap.parse_args(argv[1:])
    fp = fingerprint(args.portable)
    if args.json:
        print(json.dumps({"inputs": fingerprint_inputs(args.portable), "fingerprint": fp}, indent=2))
    else:
        print(fp)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

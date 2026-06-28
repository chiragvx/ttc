"""text-to-cad CLI — the runtime backbone as a runnable program.

  python -m packages.cli status
  python -m packages.cli propose "make the skin 3 mm"

Uses OpenRouter (DeepSeek) when OPENROUTER_API_KEY is set; with no key there is NO LLM (it says so).
A proposal is AI-PROPOSED only (previewed via the rules validator); committing + sign-off + a grounded
FS are what make a design export-eligible.
"""

from __future__ import annotations

import argparse
import sys

from packages.agents.llm_provider import LLMProvider
from packages.agents.provider_factory import get_provider
from packages.agents.runtime import CoModelingSession, ProposeResult
from packages.ledger.branch import iter_parameters
from packages.ledger.events import EventLog
from packages.ledger.gates import evaluate_export_gates
from packages.transport.app import make_demo_ledger

_TS = "2026-06-28T00:00:00Z"


def _new_session(provider: LLMProvider | None = None) -> CoModelingSession:
    log = EventLog()
    log.append_genesis(make_demo_ledger(), actor="system", ts=_TS)
    return CoModelingSession(provider or get_provider(), log)


def run_once(intent: str, *, provider: LLMProvider | None = None) -> tuple[CoModelingSession, ProposeResult]:
    session = _new_session(provider)
    return session, session.propose(intent, ts=_TS)


def _print_status(session: CoModelingSession) -> None:
    led = session.log.fold()
    print("parameters:")
    for path, pd in iter_parameters(led):
        lock = "  [HARD_LOCK]" if pd.is_locked else ""
        print(f"  {path} = {pd.value} {pd.unit}{lock}  bounds={pd.bounds}")
    gate = evaluate_export_gates(led)
    print(f"export: {gate.status.value}" + (f"  ({'; '.join(gate.reasons)})" if gate.reasons else ""))


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(prog="text-to-cad", description="Grounded text-to-CAD runtime CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("propose", help="propose parameter changes from a natural-language intent")
    p.add_argument("intent")
    sub.add_parser("status", help="show current parameters + export gate")
    args = ap.parse_args(argv)

    if args.cmd == "status":
        _print_status(_new_session())
        return 0

    provider = get_provider()
    if provider is None:
        print("No LLM configured — set OPENROUTER_API_KEY (see .env.example).")
        _print_status(_new_session())
        return 0

    session, result = run_once(args.intent, provider=provider)
    if result.needs_clarification:
        print(f"? clarification needed: {result.proposal.request_clarification}")
    elif not result.proposal.deltas:
        print("(no parameter change proposed)")
    else:
        for delta, outcome in zip(result.proposal.deltas, result.trial_outcomes):
            extra = f" — {outcome.message}" if outcome.message else ""
            print(f"proposed {delta.target_node} -> {delta.requested_value}: {outcome.status.value}{extra}")
        print("(AI-proposed only — accept + engineer sign-off + a grounded FS are required to export)")
    _print_status(session)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

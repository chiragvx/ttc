"""Per-design cost accounting via USAGE events + summary projection."""

from __future__ import annotations

import math

from packages.ledger.cost import Usage, record_usage, summarize
from packages.ledger.events import EventLog

TS = "2026-06-28T00:00:00Z"


def test_usage_cost_per_million_tokens():
    u = Usage(model="deepseek/deepseek-chat", tokens_in=1_000_000, tokens_out=1_000_000)
    assert math.isclose(u.cost_usd(), 0.14 + 0.28)  # in + out per 1M


def test_unknown_model_is_zero_cost():
    assert Usage(model="mystery", tokens_in=10_000).cost_usd() == 0.0


def test_summary_accumulates_and_does_not_break_replay(base_ledger):
    log = EventLog()
    log.append_genesis(base_ledger, actor="system", ts=TS)
    record_usage(log, Usage("deepseek/deepseek-chat", 1000, 500), ts=TS, actor="agent")
    record_usage(log, Usage(solver_seconds=12.5), ts=TS, actor="solver")

    s = summarize(log)
    assert s.n_calls == 2
    assert s.tokens_in == 1000 and s.tokens_out == 500
    assert math.isclose(s.solver_seconds, 12.5)
    assert s.usd > 0
    # USAGE events are recorded but don't change ledger state
    assert log.fold().instances["root"].params["skin_thickness_mm"].value == 2.0
    assert log.verify_chain() is True

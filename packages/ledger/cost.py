"""Per-design cost / token / compute accounting — recorded as USAGE events, summarized on demand.

Closes the observability gap: every LLM call and solver run logs a `USAGE` event, so cost-per-design
is an auditable projection over the event log (not a guess). Prices are per-1M-tokens; extend the
table per model. Solver compute time is tracked in seconds.
"""

from __future__ import annotations

from dataclasses import dataclass

from packages.ledger.events import BaseEventLog, EventKind

# (input, output) USD per 1M tokens — representative OpenRouter/DeepSeek pricing; update as needed.
PRICES_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    "deepseek/deepseek-chat": (0.14, 0.28),
    "deepseek/deepseek-r1": (0.55, 2.19),
}


@dataclass(frozen=True)
class Usage:
    model: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    solver_seconds: float = 0.0

    def cost_usd(self) -> float:
        pin, pout = PRICES_USD_PER_MTOK.get(self.model, (0.0, 0.0))
        return (self.tokens_in * pin + self.tokens_out * pout) / 1_000_000.0


def record_usage(log: BaseEventLog, usage: Usage, *, ts: str, actor: str = "system") -> None:
    log.append_usage({"model": usage.model, "tokens_in": usage.tokens_in,
                      "tokens_out": usage.tokens_out, "solver_seconds": usage.solver_seconds,
                      "cost_usd": round(usage.cost_usd(), 6)}, actor=actor, ts=ts)


@dataclass
class CostSummary:
    tokens_in: int = 0
    tokens_out: int = 0
    usd: float = 0.0
    solver_seconds: float = 0.0
    n_calls: int = 0


def summarize(log: BaseEventLog) -> CostSummary:
    s = CostSummary()
    for ev in log.events():
        if ev.kind is EventKind.USAGE:
            p = ev.payload
            s.tokens_in += int(p.get("tokens_in", 0))
            s.tokens_out += int(p.get("tokens_out", 0))
            s.usd += float(p.get("cost_usd", 0.0))
            s.solver_seconds += float(p.get("solver_seconds", 0.0))
            s.n_calls += 1
    s.usd = round(s.usd, 6)
    return s

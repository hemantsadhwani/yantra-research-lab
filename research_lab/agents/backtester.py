"""Backtester agent — runs a variant on the synthetic engine.

In production this call goes through an MCP tool (`run_backtest`) so any host/agent
can drive the engine and the boundary stays clean. Here it calls the in-process
public engine directly; the MCP wrapper lives in ``mcp_server/``. See ADR-0002.

The ``strategy`` selector names which engine to drive — the same agent loop drives a
synthetic stand-in here or a private production strategy server-side, unchanged.
"""

from __future__ import annotations

from research_lab.schemas import BacktestResult, StrategyVariant
from synthetic_engine import DEFAULT_STRATEGY, run_backtest


class Backtester:
    def __init__(self, strategy: str = DEFAULT_STRATEGY) -> None:
        self.strategy = strategy

    def backtest(self, variant: StrategyVariant) -> BacktestResult:
        m = run_backtest(variant.params, strategy=self.strategy)
        return BacktestResult(
            variant_id=variant.id,
            total_return_pct=m["total_return_pct"],
            trades=m["trades"],
            win_rate=m["win_rate"],
            max_drawdown_pct=m["max_drawdown_pct"],
            sharpe=m["sharpe"],
        )

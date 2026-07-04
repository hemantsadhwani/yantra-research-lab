"""Backtester agent — runs a variant on the synthetic engine.

In production this call goes through an MCP tool (`run_backtest`) so any host/agent
can drive the engine and the boundary stays clean. Here it calls the in-process
public engine directly; the MCP wrapper lives in ``mcp_server/``. See ADR-0002.
"""

from __future__ import annotations

from research_lab.schemas import BacktestResult, StrategyVariant
from synthetic_engine import run_backtest


class Backtester:
    def backtest(self, variant: StrategyVariant) -> BacktestResult:
        m = run_backtest(variant.params)
        return BacktestResult(
            variant_id=variant.id,
            total_return_pct=m["total_return_pct"],
            trades=m["trades"],
            win_rate=m["win_rate"],
            max_drawdown_pct=m["max_drawdown_pct"],
            sharpe=m["sharpe"],
        )

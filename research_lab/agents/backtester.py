"""Backtester agent — runs a variant on the synthetic engine.

In production this call goes through an MCP tool (`run_backtest`) so any host/agent
can drive the engine and the boundary stays clean. ``Backtester`` calls the in-process
public engine directly; ``MCPBacktester`` drives the same engine through the MCP server in
``mcp_server/`` over stdio. ``make_backtester(engine, strategy)`` picks one. See ADR-0002.

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


def _result_from_metrics(variant_id: str, m: dict) -> BacktestResult:
    return BacktestResult(
        variant_id=variant_id,
        total_return_pct=m["total_return_pct"],
        trades=m["trades"],
        win_rate=m["win_rate"],
        max_drawdown_pct=m["max_drawdown_pct"],
        sharpe=m["sharpe"],
    )


class MCPBacktester:
    """Same ``.backtest(variant)`` contract as ``Backtester``, but over MCP stdio.

    Calls the ``run_backtest`` tool of ``python -m mcp_server.server`` through a
    ``BacktestMCPClient``. The client (and so the ``mcp`` SDK) is created lazily, so merely
    importing this module never pulls in ``mcp``.
    """

    def __init__(self, strategy: str = DEFAULT_STRATEGY, client=None) -> None:
        self.strategy = strategy
        self._client = client

    @property
    def client(self):
        if self._client is None:
            from research_lab.mcp_client import BacktestMCPClient
            self._client = BacktestMCPClient()
        return self._client

    def backtest(self, variant: StrategyVariant) -> BacktestResult:
        m = self.client.call_tool("run_backtest",
                                  {"params": variant.params, "strategy": self.strategy})
        return _result_from_metrics(variant.id, m)


# One MCP server per process: every MCPBacktester built by the factory shares it (strategy
# is a per-call argument, so a single server serves all strategies).
_MCP_CLIENT = None
ENGINES = ("inprocess", "mcp")


def _shared_mcp_client():
    global _MCP_CLIENT
    if _MCP_CLIENT is None:
        from research_lab.mcp_client import BacktestMCPClient
        _MCP_CLIENT = BacktestMCPClient()
    return _MCP_CLIENT


def make_backtester(engine: str, strategy: str = DEFAULT_STRATEGY):
    """``"inprocess"`` -> ``Backtester``; ``"mcp"`` -> ``MCPBacktester`` on a shared client."""
    if engine == "inprocess":
        return Backtester(strategy=strategy)
    if engine == "mcp":
        return MCPBacktester(strategy=strategy, client=_shared_mcp_client())
    raise ValueError(f"unknown engine {engine!r}; choose from {list(ENGINES)}")


def close_mcp_clients() -> None:
    """Shut down the shared MCP server subprocess, if one was started."""
    global _MCP_CLIENT
    client, _MCP_CLIENT = _MCP_CLIENT, None
    if client is not None:
        client.close()

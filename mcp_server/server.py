"""MCP tool server over the synthetic engine.

Wrapping the engine as MCP tools means any host (Claude Desktop, an IDE, another agent)
can drive backtests through a stable contract — the boundary the Backtester agent uses in
production. Tier-1 calls the engine in-process; this exposes the same capability over MCP.

Run (needs `pip install '.[mcp]'`):
    python -m mcp_server.server

The tool contract (stable regardless of transport):
    run_backtest(params: {lookback, z_entry, z_exit, stop_pct}, strategy?) -> {total_return_pct,
                 trades, win_rate, max_drawdown_pct, sharpe}
    get_param_space() -> {name: [min, max]}
    get_baseline(strategy?) -> params
    list_strategies() -> [name, ...]

``strategy`` selects which engine to drive. Here every strategy resolves to a synthetic
stand-in; in production the same contract fronts the private production strategies, so an
agent host cannot tell (nor need to) whether it is driving the public or the real engine.
"""

from __future__ import annotations

from synthetic_engine import (
    DEFAULT_STRATEGY,
    PARAM_SPACE,
    get_baseline as _get_baseline,
    list_strategies as _list_strategies,
    run_backtest,
)


def _register(mcp) -> None:  # pragma: no cover - thin adapter
    @mcp.tool()
    def run_backtest_tool(params: dict, strategy: str = DEFAULT_STRATEGY) -> dict:
        """Backtest one strategy variant on the public synthetic engine."""
        return run_backtest(params, strategy=strategy)

    @mcp.tool()
    def get_param_space() -> dict:
        """Return the tunable parameters and their valid ranges."""
        return {k: list(v) for k, v in PARAM_SPACE.items()}

    @mcp.tool()
    def get_baseline(strategy: str = DEFAULT_STRATEGY) -> dict:
        """Return the baseline parameters every variant is judged against."""
        return _get_baseline(strategy)

    @mcp.tool()
    def list_strategies() -> list:
        """List the strategies an agent host can target (synthetic stand-ins here)."""
        return _list_strategies()


def main() -> None:  # pragma: no cover
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # keep Tier-1 dependency-free
        raise SystemExit("MCP not installed. Run: pip install '.[mcp]'") from exc
    mcp = FastMCP("yantra-backtest")
    _register(mcp)
    mcp.run()


if __name__ == "__main__":
    main()

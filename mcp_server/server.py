"""MCP tool server over the synthetic engine.

Wrapping the engine as MCP tools means any host (Claude Desktop, an IDE, another agent)
can drive backtests through a stable contract — the boundary the Backtester agent uses in
production. Tier-1 calls the engine in-process; this exposes the same capability over MCP.

Run (needs `pip install '.[mcp]'`):
    python -m mcp_server.server

The tool contract (stable regardless of transport):
    run_backtest(params: {lookback, z_entry, z_exit, stop_pct}) -> {total_return_pct, trades,
                 win_rate, max_drawdown_pct, sharpe}
    get_param_space() -> {name: [min, max]}
    get_baseline() -> params
"""

from __future__ import annotations

from synthetic_engine import BASELINE_PARAMS, PARAM_SPACE, run_backtest


def _register(mcp) -> None:  # pragma: no cover - thin adapter
    @mcp.tool()
    def run_backtest_tool(params: dict) -> dict:
        """Backtest one strategy variant on the public synthetic engine."""
        return run_backtest(params)

    @mcp.tool()
    def get_param_space() -> dict:
        """Return the tunable parameters and their valid ranges."""
        return {k: list(v) for k, v in PARAM_SPACE.items()}

    @mcp.tool()
    def get_baseline() -> dict:
        """Return the baseline parameters every variant is judged against."""
        return dict(BASELINE_PARAMS)


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

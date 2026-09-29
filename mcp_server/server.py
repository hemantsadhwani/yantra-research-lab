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

from typing import Any

from synthetic_engine import (
    DEFAULT_STRATEGY,
    PARAM_SPACE,
    run_backtest,
)
from synthetic_engine import (
    get_baseline as _get_baseline,
)
from synthetic_engine import (
    list_strategies as _list_strategies,
)


def _register(mcp) -> None:  # pragma: no cover - thin adapter
    # Registered under the contract name (``run_backtest``); the Python name differs only
    # to avoid shadowing the engine function imported above.
    @mcp.tool(name="run_backtest", structured_output=True)
    def run_backtest_tool(params: dict[str, float],
                          strategy: str = DEFAULT_STRATEGY) -> dict[str, Any]:
        """Backtest one strategy variant on the public synthetic engine."""
        # A plain dict of the BacktestResult metric fields -> FastMCP fills structuredContent.
        return dict(run_backtest(params, strategy=strategy))

    # structured_output=True + parameterised return types: FastMCP only fills
    # ``structuredContent`` when it can build an output schema. A bare ``list`` return is
    # otherwise split into one TextContent per item.
    @mcp.tool(structured_output=True)
    def get_param_space() -> dict[str, list[float]]:
        """Return the tunable parameters and their valid ranges."""
        return {k: list(v) for k, v in PARAM_SPACE.items()}

    @mcp.tool(structured_output=True)
    def get_baseline(strategy: str = DEFAULT_STRATEGY) -> dict[str, float]:
        """Return the baseline parameters every variant is judged against."""
        return _get_baseline(strategy)

    @mcp.tool(structured_output=True)
    def list_strategies() -> list[str]:
        """List the strategies an agent host can target (synthetic stand-ins here)."""
        return _list_strategies()


def main() -> None:  # pragma: no cover
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # keep Tier-1 dependency-free
        raise SystemExit("MCP not installed. Run: pip install '.[mcp]'") from exc
    # WARNING: FastMCP logs every request at INFO to stderr, which a stdio host
    # (e.g. ``research_lab.mcp_client``) would echo into its own console.
    mcp = FastMCP("yantra-backtest", log_level="WARNING")
    _register(mcp)
    mcp.run()


if __name__ == "__main__":
    main()

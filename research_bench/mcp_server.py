"""The bench's engine tools as an MCP server (stdio), over the public quant_engine.

    python -m research_bench.mcp_server            # needs the mcp extra

A private server serves the same tool names over real backtests and returns metrics only; the
bench connects with ``MCPEngine(argv=[...])`` and nothing else changes. The holdout seal lives
here, in ``BENCH_SEAL_DB`` (default ``.cache/holdout_seals.sqlite``), so a client cannot reopen a
study's holdout and every opening is counted.
"""

from __future__ import annotations

import os
from typing import Any

from research_bench.engine import LocalEngine, Seal


def build_server(engine: Any = None):  # pragma: no cover - thin adapter, exercised via MCPEngine tests
    from mcp.server.fastmcp import FastMCP

    eng = engine or LocalEngine(Seal(os.environ.get("BENCH_SEAL_DB", ".cache/holdout_seals.sqlite")))
    mcp = FastMCP("research-bench")

    @mcp.tool(structured_output=True)
    def catalogue() -> dict[str, Any]:
        """Templates, their parameter grids and the filters the bench may use."""
        return eng.catalogue()

    @mcp.tool(structured_output=True)
    def dataset_card(source: str) -> dict[str, Any]:
        """Rows, date range, quality checks and content hash of a data source."""
        return eng.dataset_card(source)

    @mcp.tool(structured_output=True)
    def run_family(source: str, template: str, space: dict[str, list[float]], fid: str,
                   round_no: int) -> dict[str, Any]:
        """Walk-forward one parameter family on development data (the holdout is never read)."""
        return eng.run_family(source, template, space, fid, round_no)

    @mcp.tool(structured_output=True)
    def diagnostics(source: str, family: dict[str, Any]) -> dict[str, Any]:
        """Where a family's best parameters make and lose money: VIX level, trend, year (dev data)."""
        return eng.diagnostics(source, family)

    @mcp.tool(structured_output=True)
    def neighbourhood(source: str, family: dict[str, Any]) -> dict[str, Any]:
        """Dev Sharpe of the best parameters' grid neighbours: a plateau or a spike."""
        return eng.neighbourhood(source, family)

    @mcp.tool(structured_output=True)
    def open_holdout(source: str, family: dict[str, Any], study: str) -> dict[str, Any]:
        """Read the sealed holdout ONCE per study; a second call for the same study is refused."""
        return eng.open_holdout(source, family, study)

    @mcp.tool(structured_output=True)
    def seal_log(source: str) -> dict[str, Any]:
        """Every holdout opening for a source: how many, by which study, for which family."""
        return eng.seal_log(source)

    return mcp


if __name__ == "__main__":
    build_server().run()

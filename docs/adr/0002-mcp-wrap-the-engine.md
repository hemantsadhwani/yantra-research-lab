# ADR-0002 — Wrap the engine as MCP tools, not direct calls only

**Status:** accepted · 2026-07-04

**Decision.** Expose the backtest engine through an **MCP server** (`mcp_server/`) as the
canonical way agents/hosts drive it. Tier-1 also calls it in-process for a zero-dependency demo,
but the production path is the MCP tool.

**Why.** MCP is the emerging **host-agnostic tool standard** — any agent, IDE, or Claude host can
call `run_backtest` through a stable contract without importing our code. It keeps a clean
boundary (the agent depends on a *tool contract*, not engine internals) and makes the capability
reusable.

**Cost/latency.** Negligible — the tool is a thin adapter; the engine call dominates.

**Consequences.** The Backtester agent targets the MCP contract; swapping the synthetic engine for
the real one (privately) is a server-side change with no agent edits.
</content>

## As built (2026-09-29)
Until WP2 only the server existed; nothing in the repo called it over MCP. Now the client does.

- **`research_lab/mcp_client.py`**: `BacktestMCPClient` starts `python -m mcp_server.server` as a
  stdio subprocess and exposes sync methods, so the sync loop drives the engine over the wire
  exactly as it does in-process. `MCPBacktester` implements the same `backtest(variant)` method
  as the in-process `Backtester`; `--engine mcp` on `run.py` and `run_graph.py` selects it.
- **Proven by test, not asserted.** `research_lab/tests/test_mcp.py::test_mcp_and_inprocess_are_byte_identical`
  runs every named strategy both ways and requires identical results; the supervisor and the
  graph over MCP produce the same rankings as in-process. The server tool is registered as
  `run_backtest`, matching the documented contract (`test_mcp_tool_names_match_docs`).
- **Three MCP details that cost time:**
  - `structuredContent` is only filled when FastMCP can build an output schema: tools need typed
    returns (`dict[str, float]`, `list[str]`) *and* `structured_output=True`. Otherwise a bare
    `list` return comes back as one `TextContent` per item.
  - Tool failures arrive as a result with `isError=True`, not as an exception. The client raises
    `MCPToolError` on them (`test_tool_error_is_raised`), so a failed backtest cannot be read as an
    empty metrics dict.
  - The stdio transport's anyio task group must be exited on the event loop that entered it. The
    client runs the async SDK on a private loop in a daemon thread and tears down on that same
    loop, because anyio refuses to exit a task group from a different task than the one that entered it.
- The server logs at `WARNING`, because FastMCP's per-request `INFO` lines on stderr otherwise
  get echoed into the host's console.

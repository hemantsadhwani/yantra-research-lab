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

"""Synchronous MCP stdio client for the backtest tool server (``mcp_server/server.py``).

``BacktestMCPClient`` starts ``python -m mcp_server.server`` as a subprocess, opens an MCP
``ClientSession`` over stdio and exposes *sync* methods, so the (sync) research loop can
drive the engine over the wire exactly as it drives it in-process. See ADR-0002.

The async MCP SDK runs on a private event loop in a daemon thread; every public method
submits a coroutine with ``asyncio.run_coroutine_threadsafe``, so calls are thread-safe
and usable from plain sync code (the stdlib supervisor, LangGraph nodes, tests).

Needs the ``mcp`` extra. This module is only ever imported lazily (``--engine mcp``), so the
stdlib default path never loads it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import threading
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, Self

REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER_MODULE = "mcp_server.server"
_TIMEOUT_S = 60.0
_log = logging.getLogger(__name__)


class MCPToolError(RuntimeError):
    """The MCP server reported ``isError`` for a tool call."""


class BacktestMCPClient:
    def __init__(self, timeout: float = _TIMEOUT_S) -> None:
        try:
            import mcp  # noqa: F401  (fail early with a clear message)
        except ImportError as exc:  # keep Tier-1 dependency-free
            raise RuntimeError("MCP not installed. Run: pip install -e '.[mcp]'") from exc
        self._timeout = timeout
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever,
                                        name="mcp-client-loop", daemon=True)
        self._thread.start()
        self._stack: AsyncExitStack | None = None
        self._session = None
        self._closed = False
        try:
            self._submit(self._connect())
        except BaseException:
            self.close()
            raise

    # ------------------------------------------------------------------ plumbing
    def _submit(self, coro):
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return fut.result(self._timeout)

    async def _connect(self) -> None:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        env = dict(os.environ)
        # The server imports ``synthetic_engine`` / ``mcp_server`` from the repo root; make
        # that work even when the package is not pip-installed.
        env["PYTHONPATH"] = os.pathsep.join(
            p for p in (str(REPO_ROOT), env.get("PYTHONPATH", "")) if p)
        params = StdioServerParameters(command=sys.executable, args=["-m", SERVER_MODULE],
                                       cwd=str(REPO_ROOT), env=env)
        stack = AsyncExitStack()
        try:
            read, write = await stack.enter_async_context(stdio_client(params))
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
        except BaseException:
            await stack.aclose()
            raise
        self._stack, self._session = stack, session

    # -------------------------------------------------------------------- public
    def list_tools(self) -> list[str]:
        async def _go():
            return await self._session.list_tools()
        return [t.name for t in self._submit(_go()).tools]

    def call_tool(self, name: str, args: dict[str, Any] | None = None) -> Any:
        if self._closed:
            raise RuntimeError("BacktestMCPClient is closed")

        async def _go():
            return await self._session.call_tool(name, args or {})
        return _parse_result(name, self._submit(_go()))

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._stack is not None:
            # The stdio transport's anyio task group must be exited from the task that
            # entered it -- both happen on the private loop, so this is safe.
            try:
                self._submit(self._stack.aclose())
            except Exception as exc:  # noqa: BLE001 - best-effort teardown; never mask the caller's error
                _log.debug("MCP client shutdown: %r", exc)
            self._stack, self._session = None, None
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)
        if not self._loop.is_running():
            self._loop.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def _parse_result(name: str, result) -> Any:
    if getattr(result, "isError", False):
        text = " ".join(getattr(c, "text", "") for c in (result.content or []))
        raise MCPToolError(f"MCP tool {name!r} failed: {text or 'no detail'}")
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        # FastMCP wraps non-object return types (e.g. a list) as {"result": ...}.
        if set(structured) == {"result"}:
            return structured["result"]
        return structured
    if result.content:
        return json.loads(result.content[0].text)
    raise MCPToolError(f"MCP tool {name!r} returned no content")

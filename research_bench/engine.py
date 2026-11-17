"""The engine seam: the bench drives any engine that serves these tools.

    catalogue() · dataset_card(source) · run_family(source, template, space, fid, round_no)
    diagnostics(source, family) · neighbourhood(source, family) · open_holdout(source, family, study)
    protocol(source, looks) -> {text, required_now, required_next}: the engine owns the success test

``LocalEngine`` runs the public quant_engine in-process. ``MCPEngine`` calls the same tool names
on an MCP server over stdio: ``research_bench.mcp_server`` (public) or a private server that
wraps real backtests and returns metrics only. The agents and the supervisor cannot tell which.

The holdout seal belongs to the engine, not to the client: every opening is logged with its
study id, a second opening for the same study is refused, and ``seal_log`` lets an auditor
count how often a dataset's holdout has been read.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Protocol

from research_bench import tools


class Engine(Protocol):
    def catalogue(self) -> dict: ...
    def dataset_card(self, source: str) -> dict: ...
    def run_family(self, source: str, template: str, space: dict, fid: str, round_no: int) -> dict: ...
    def diagnostics(self, source: str, family: dict) -> dict: ...
    def neighbourhood(self, source: str, family: dict) -> dict: ...
    def open_holdout(self, source: str, family: dict, study: str) -> dict: ...
    def protocol(self, source: str, looks: int) -> dict: ...   # {text, required_now, required_next}


class HoldoutSealed(RuntimeError):
    """The holdout was already opened for this study."""


class Seal:
    """Who opened which holdout, when. SQLite so a server keeps it across restarts."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = threading.Lock()
        self._db.execute("CREATE TABLE IF NOT EXISTS openings (source TEXT, study TEXT, family TEXT, "
                         "at REAL, PRIMARY KEY (source, study))")

    def claim(self, source: str, study: str, family: str) -> None:
        with self._lock, self._db:
            try:
                self._db.execute("INSERT INTO openings VALUES (?, ?, ?, ?)", (source, study, family, time.time()))
            except sqlite3.IntegrityError:
                raise HoldoutSealed(f"holdout of {source!r} already opened for study {study!r}") from None

    def log(self, source: str) -> dict:
        with self._lock:
            rows = self._db.execute("SELECT study, family, at FROM openings WHERE source = ? ORDER BY at",
                                    (source,)).fetchall()
        return {"source": source, "openings": len(rows),
                "studies": [{"study": s, "family": f, "at": round(a)} for s, f, a in rows]}


class LocalEngine:
    def __init__(self, seal: Seal | None = None) -> None:
        self.seal = seal or Seal()

    def catalogue(self) -> dict:
        return tools.catalogue()

    def dataset_card(self, source: str) -> dict:
        return tools.card(source)

    def run_family(self, source: str, template: str, space: dict, fid: str, round_no: int) -> dict:
        return tools.run_family(source, template, space, fid, round_no)

    def diagnostics(self, source: str, family: dict) -> dict:
        return tools.diagnostics(source, family)

    def neighbourhood(self, source: str, family: dict) -> dict:
        return tools.neighbourhood(source, family)

    def open_holdout(self, source: str, family: dict, study: str) -> dict:
        self.seal.claim(source, study, family["id"])
        return tools.open_holdout(source, family)

    def seal_log(self, source: str) -> dict:
        return self.seal.log(source)

    def protocol(self, source: str, looks: int) -> dict:
        from research_bench.agents import SUCCESS_TEST
        return {"text": SUCCESS_TEST, "required_now": tools.required_oos_sharpe(looks),
                "required_next": tools.required_oos_sharpe(looks + 1)}


class MCPEngine:
    """The same tools over MCP stdio. ``argv`` launches the server; default: the public one."""

    def __init__(self, argv: list[str] | None = None, cwd: str | None = None, timeout: float = 600.0) -> None:
        from research_lab.mcp_client import BacktestMCPClient
        self._c = BacktestMCPClient(timeout=timeout, module="research_bench.mcp_server", argv=argv, cwd=cwd)
        self._cat: dict | None = None

    def _call(self, name: str, **args: Any) -> Any:
        return self._c.call_tool(name, args)

    def catalogue(self) -> dict:
        if self._cat is None:
            self._cat = self._call("catalogue")
        return self._cat

    def dataset_card(self, source: str) -> dict:
        return self._call("dataset_card", source=source)

    def run_family(self, source: str, template: str, space: dict, fid: str, round_no: int) -> dict:
        return self._call("run_family", source=source, template=template, space=space, fid=fid, round_no=round_no)

    def diagnostics(self, source: str, family: dict) -> dict:
        return self._call("diagnostics", source=source, family=family)

    def neighbourhood(self, source: str, family: dict) -> dict:
        return self._call("neighbourhood", source=source, family=family)

    def open_holdout(self, source: str, family: dict, study: str) -> dict:
        return self._call("open_holdout", source=source, family=family, study=study)

    def seal_log(self, source: str) -> dict:
        return self._call("seal_log", source=source)

    def protocol(self, source: str, looks: int) -> dict:
        return self._call("protocol", source=source, looks=looks)

    def close(self) -> None:
        self._c.close()

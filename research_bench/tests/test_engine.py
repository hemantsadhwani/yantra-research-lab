"""The engine seam: the holdout seal, and the same study over MCP as in-process."""

from __future__ import annotations

import pytest

from research_bench.agents import OfflineAgents
from research_bench.engine import HoldoutSealed, LocalEngine, Seal
from research_bench.graph import build, new_state

SRC = "synthetic:trend:1002"   # calibration seed


def test_seal_refuses_a_second_opening_and_counts_every_one(tmp_path) -> None:
    seal = Seal(tmp_path / "seals.sqlite")
    seal.claim(SRC, "study-a", "F1")
    with pytest.raises(HoldoutSealed):
        seal.claim(SRC, "study-a", "F2")
    seal.claim(SRC, "study-b", "F1")
    assert Seal(tmp_path / "seals.sqlite").log(SRC)["openings"] == 2      # survives a restart


def _run(engine, study: str) -> dict:
    return build(OfflineAgents(), engine=engine, study=study).invoke(
        new_state("Ride sustained trends", SRC, mode="benchmark"), {"recursion_limit": 60})


def test_study_over_mcp_matches_in_process(tmp_path, monkeypatch) -> None:
    pytest.importorskip("mcp")
    from research_bench.engine import MCPEngine
    from research_lab.mcp_client import MCPToolError

    monkeypatch.setenv("BENCH_SEAL_DB", str(tmp_path / "server_seals.sqlite"))
    local = _run(LocalEngine(), "s1")
    eng = MCPEngine()
    try:
        remote = _run(eng, "s1")
        key = [(f["template"], f["trials"], f["oos_sharpe"], f["passed_walk_forward"])
               for f in local["ledger"]["families"]]
        assert key == [(f["template"], f["trials"], f["oos_sharpe"], f["passed_walk_forward"])
                       for f in remote["ledger"]["families"]]
        assert local["verdict"] == remote["verdict"]
        if remote.get("holdout"):                                         # the server holds the seal
            best = next(f for f in remote["ledger"]["families"] if f["id"] == remote["verdict"]["family"])
            with pytest.raises(MCPToolError, match="already opened"):
                eng.open_holdout(SRC, best, "s1")
            assert eng.seal_log(SRC)["openings"] == 1
    finally:
        eng.close()

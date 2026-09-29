"""One contract, two engines: the loop drives the backtest engine over MCP stdio and gets
exactly what it gets in-process. Offline — no API key. Skipped without the ``mcp`` extra."""
from __future__ import annotations

import pytest

pytest.importorskip("mcp")

from research_lab.agents.backtester import Backtester, MCPBacktester
from research_lab.agents.evaluator import score_result
from research_lab.mcp_client import BacktestMCPClient
from research_lab.schemas import StrategyVariant
from research_lab.supervisor import Supervisor
from synthetic_engine import get_baseline

NAMED = ["nifty-weekday", "nifty-expiry", "sensex-expiry"]


@pytest.fixture(scope="module")
def client():
    c = BacktestMCPClient()
    yield c
    c.close()


def test_mcp_tool_names_match_docs(client):
    assert set(client.list_tools()) == {
        "run_backtest", "get_param_space", "get_baseline", "list_strategies",
    }


@pytest.mark.parametrize("strategy", NAMED)
def test_mcp_and_inprocess_are_byte_identical(client, strategy):
    v = StrategyVariant(id="baseline", params=get_baseline(strategy), rationale="baseline")
    over_mcp = MCPBacktester(strategy=strategy, client=client).backtest(v)
    in_process = Backtester(strategy=strategy).backtest(v)
    assert over_mcp == in_process          # exact dataclass equality, no tolerance


def test_supervisor_accepts_mcp_backtester(client):
    run = Supervisor(seed=3, backtester=MCPBacktester(client=client)).run(2, 3)
    assert run.variants_tested == 6
    assert run.best is not None
    assert run.best.evaluation.score > score_result(run.baseline)
    # ...and it is the same run the in-process engine produces.
    ref = Supervisor(seed=3).run(2, 3)
    assert [(r.variant.id, r.evaluation.score) for r in run.ranked] == \
           [(r.variant.id, r.evaluation.score) for r in ref.ranked]


def test_tool_error_is_raised(client):
    with pytest.raises(RuntimeError, match="unknown strategy"):
        client.call_tool("run_backtest", {"params": get_baseline("nifty-expiry"),
                                          "strategy": "does-not-exist"})

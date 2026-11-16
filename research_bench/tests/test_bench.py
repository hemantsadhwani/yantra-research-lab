"""The bench, offline: the graph runs end to end, code clamps what agents propose, the looks bar
rises, the holdout opens at most once, the human gate interrupts, and report numbers are checked."""

from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from research_bench import checker, tools
from research_bench.agents import OfflineAgents
from research_bench.graph import build, new_state
from research_bench.schemas import Experiment, Report, RoundProposal, StrategySpec

SRC = "synthetic:meanrev:1003"   # a calibration seed, never a benchmark seed


def test_benchmark_mode_runs_to_a_verdict_without_a_human() -> None:
    out = build(OfflineAgents()).invoke(new_state("Buy short-term oversold dips", SRC, mode="benchmark"),
                                        {"recursion_limit": 60})
    assert out["verdict"]["decision"] in ("promote?", "reject") and out["stop_reason"]
    assert out["ledger"]["trials"] == sum(f["trials"] for f in out["ledger"]["families"])
    assert out["ledger"]["looks"] == len(out["ledger"]["families"]) and "report" not in out


def test_clamp_keeps_catalogue_values_and_reports_the_rest() -> None:
    sub, dropped = tools.clamp("ema_cross", {"fast": [10, 11], "vix_max": [25], "bogus": [1]})
    assert sub["fast"] == [10] and sub["slow"] == [50, 100, 150, 200] and sub["vix_max"] == [25]
    assert sub["trend_ema"] == [0] and "fast=11" in dropped and "bogus (not a parameter)" in dropped
    with pytest.raises(ValueError):
        tools.clamp("magic", {})


def test_the_bar_rises_with_looks() -> None:
    assert tools.required_oos_sharpe(1) == 0.4
    assert tools.required_oos_sharpe(4) == pytest.approx(0.6)
    assert tools.required_oos_sharpe(8) > tools.required_oos_sharpe(4)


class Greedy(OfflineAgents):
    """A researcher that asks for far too much and for things outside the plan."""

    def research(self, state):
        exps = [Experiment(template="ema_cross", params={"trend_ema": [0, 100, 200], "vix_max": [0, 20, 25, 30],
                                                          "atr_stop": [0, 2.0, 3.0]}, rationale="everything"),
                Experiment(template="fib_pullback", params={}, rationale="not in plan")]
        return RoundProposal(diagnosis="", hypothesis="", experiments=exps), self.NONE


def test_code_refuses_over_budget_and_off_plan_experiments() -> None:
    out = build(Greedy()).invoke(new_state("Ride sustained trends", "synthetic:trend:1001", mode="benchmark"),
                                 {"recursion_limit": 60})
    led = out["ledger"]
    assert led["families"] == [] and led["trials"] == 0
    assert any("over budget" in d for d in led["dropped"]) and any("not in plan" in d for d in led["dropped"])
    assert out["verdict"]["decision"] == "reject" and "holdout" not in out


class Asks(OfflineAgents):
    def intake(self, state):
        spec, use = super().intake(state)
        if not state["answers"]:
            spec = StrategySpec(**{**spec.model_dump(), "questions": ["Reversal or continuation?"]})
        return spec, use


def test_interactive_run_asks_then_stops_at_the_human_gate() -> None:
    g = build(Asks(), checkpointer=MemorySaver())
    cfg = {"configurable": {"thread_id": "t1"}, "recursion_limit": 60}
    first = g.invoke(new_state("Trade NIFTY", "synthetic:trend:1004"), cfg)
    assert first["__interrupt__"][0].value == {"questions": ["Reversal or continuation?"]}
    out = g.invoke(Command(resume="continuation"), cfg)
    assert out["answers"] == ["continuation"]
    if out["verdict"]["decision"] == "promote?":
        assert out["__interrupt__"][0].value["verdict"]["decision"] == "promote?"
        done = g.invoke(Command(resume="approve"), cfg)
        assert done["human"] == "approve"
    assert out["report"]["title"] and out["report_check"]["passed"]


def test_checker_flags_numbers_not_in_the_facts() -> None:
    facts = {"families": [{"oos_sharpe": 0.734, "trials": 16}], "holdout": {"sharpe": -0.596}}
    ok = "OOS Sharpe 0.73 over 16 trials; the holdout Sharpe was -0.60."
    assert checker.unsupported(ok, facts) == []
    assert checker.unsupported("A Sharpe of 1.25 and 47% return.", facts) == ["1.25", "47"]


def test_report_with_invented_numbers_is_repaired_or_flagged() -> None:
    class Liar(OfflineAgents):
        def report(self, state, facts, fix=None):
            return Report(title="t", summary="Returned 99.9% a year.", findings=[], verdict="v"), self.NONE

    out = build(Liar(), checkpointer=MemorySaver()).invoke(
        new_state("Buy short-term oversold dips", SRC), {"configurable": {"thread_id": "t2"}, "recursion_limit": 60})
    assert out["report_check"] == {"unsupported_numbers": ["99.9"], "passed": False}

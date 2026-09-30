"""The LangGraph port: same loop, checkpointed, with a real human interrupt before promotion.

Offline — no API key, no network. Skipped when the ``agents`` extra is not installed.
"""
from __future__ import annotations

import pytest

pytest.importorskip("langgraph")

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from research_lab.graph import (
    best_ranked,
    build_graph,
    default_checkpointer,
    initial_state,
)

ITER, VARS, SEED = 5, 6, 3


def _start(graph, thread: str = "t"):
    cfg = {"configurable": {"thread_id": thread}}
    first = graph.invoke(initial_state(seed=SEED, iterations=ITER, variants_per_iter=VARS), cfg)
    return cfg, first


def _run_to_end(decision: str = "approve"):
    graph = build_graph(InMemorySaver())
    cfg, first = _start(graph)
    if "__interrupt__" in first:
        return graph.invoke(Command(resume=decision), cfg)
    return first


def test_graph_beats_baseline_seed3():
    final = _run_to_end()
    assert len(final["ranked"]) == ITER * VARS
    best = final["ranked"][0]
    assert best == best_ranked(final["ranked"])
    assert best["evaluation"]["score"] > final["baseline_score"]
    assert best["evaluation"]["verdict"] == "promote?"


def test_graph_is_deterministic():
    def ids_scores(state):
        return [(d["variant"]["id"], d["evaluation"]["score"]) for d in state["ranked"]]

    assert ids_scores(_run_to_end()) == ids_scores(_run_to_end())


def test_pauses_at_gate_and_resumes_with_approval(tmp_path):
    graph = build_graph(default_checkpointer(tmp_path / "ck.sqlite"))
    cfg, first = _start(graph)
    assert "__interrupt__" in first
    assert graph.get_state(cfg).next == ("gate",)
    assert graph.get_state(cfg).values.get("approval") is None   # nothing promoted yet
    final = graph.invoke(Command(resume="approve"), cfg)
    assert final["approval"] == "approved"
    assert final["promoted_id"] == best_ranked(final["ranked"])["variant"]["id"]
    assert graph.get_state(cfg).next == ()


def test_resume_survives_process_restart(tmp_path):
    db = tmp_path / "ck.sqlite"
    cfg, first = _start(build_graph(default_checkpointer(db)))
    assert "__interrupt__" in first
    # A brand-new graph + saver on the same file stands in for a new process.
    graph2 = build_graph(default_checkpointer(db))
    assert graph2.get_state(cfg).next == ("gate",)
    final = graph2.invoke(Command(resume="approve"), cfg)
    assert final["approval"] == "approved"
    assert final["promoted_id"] == _run_to_end()["promoted_id"]


def test_reject_never_promotes(tmp_path):
    graph = build_graph(default_checkpointer(tmp_path / "ck.sqlite"))
    cfg, _ = _start(graph)
    final = graph.invoke(Command(resume="reject"), cfg)
    assert final["approval"] == "rejected"
    assert final["promoted_id"] is None


def test_every_proposal_evaluated_once():
    final = _run_to_end()
    ids = [d["variant"]["id"] for d in final["ranked"]]
    assert len(ids) == len(set(ids)) == ITER * VARS
    assert len(final["trials"]) == ITER * VARS


def test_graph_runs_over_mcp():
    pytest.importorskip("mcp")
    from research_lab.agents.backtester import close_mcp_clients

    def run(engine: str):
        graph = build_graph(InMemorySaver())
        cfg = {"configurable": {"thread_id": f"t-{engine}"}}
        first = graph.invoke(initial_state(seed=3, iterations=2, variants_per_iter=3,
                                           engine=engine), cfg)
        if "__interrupt__" in first:
            return graph.invoke(Command(resume="approve"), cfg)
        return first

    try:
        over_mcp = run("mcp")
    finally:
        close_mcp_clients()
    in_process = run("inprocess")
    assert len(over_mcp["ranked"]) == 6

    def ids_scores(state):
        return [(d["variant"]["id"], d["evaluation"]["score"]) for d in state["ranked"]]

    assert ids_scores(over_mcp) == ids_scores(in_process)
    assert over_mcp["baseline"] == in_process["baseline"]


def test_route_after_record_stops_on_budget():
    from research_lab.graph import route_after_record

    promote = [{"variant": {"id": "v1"}, "evaluation": {"score": 9.0, "verdict": "promote?"}}]
    hold = [{"variant": {"id": "v1"}, "evaluation": {"score": 1.0, "verdict": "hold"}}]
    base = {"iteration": 1, "iterations": 5}
    assert route_after_record({**base, "ranked": promote}) == "propose"
    assert route_after_record({**base, "ranked": promote, "stop_reason": "budget"}) == "gate"
    assert route_after_record({**base, "ranked": hold, "stop_reason": "budget"}) == "finalize"


def test_initial_state_budget_defaults_unbounded():
    s = initial_state(max_usd=0.05, max_llm_calls=3)
    assert s["budget"] == {"max_usd": 0.05, "max_llm_calls": 3, "spent_usd": 0.0,
                           "llm_calls": 0}
    assert initial_state()["budget"]["max_usd"] is None


def test_heuristic_graph_footer():
    from research_lab.run_graph import budget_footer

    final = _run_to_end()
    assert final["budget"]["llm_calls"] == 0
    assert budget_footer(final) == "budget: $0.0000/∞ · llm calls 0/∞ · stopped: iterations"

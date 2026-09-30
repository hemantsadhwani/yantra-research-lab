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


def _cli(*args: str, db, timeout: float = 120):
    import os
    import subprocess
    import sys
    env = {**os.environ, "ANTHROPIC_API_KEY": "", "LOGFIRE_TOKEN": "", "YANTRA_ENV": "test"}
    return subprocess.run([sys.executable, "-m", "research_lab.run_graph", *args,
                           "--db", str(db)], capture_output=True, text=True, env=env, check=False,
                          timeout=timeout)


def _list_line(db, thread: str) -> str:
    out = _cli("--list", db=db).stdout
    lines = [ln for ln in out.splitlines() if ln.strip().startswith(thread + " ")]
    assert lines, out
    return lines[0]


def test_cli_resume_continues_a_crashed_run(tmp_path):
    """SIGKILL a CLI run mid-loop, then ``--resume <thread>`` (no decision) finishes it,
    and lands on exactly the result of a run that was never interrupted."""
    import os
    import re
    import signal
    import subprocess
    import sys

    cfg = ["--iterations", "40", "--variants", "2", "--seed", "3", "--no-gate"]
    db = tmp_path / "ckpt.sqlite"
    env = {**os.environ, "ANTHROPIC_API_KEY": "", "LOGFIRE_TOKEN": "", "YANTRA_ENV": "test",
           "PYTHONUNBUFFERED": "1"}
    proc = subprocess.Popen(
        [sys.executable, "-m", "research_lab.run_graph", *cfg, "--db", str(db),
         "--thread", "crash1"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
    # Kill on progress rather than a wall-clock delay: interpreter start-up time varies by
    # machine, but "iter 2/" guarantees at least one iteration is checkpointed.
    seen = []
    for line in proc.stdout:
        seen.append(line)
        if " iter 2/" in line:
            proc.send_signal(signal.SIGKILL)
            break
    proc.wait(timeout=30)
    assert proc.returncode == -signal.SIGKILL, "".join(seen)
    print("".join(seen), end="")

    killed = _list_line(db, "crash1")
    print(killed)
    assert "PAUSED at gate" not in killed and "next: " in killed, killed
    done_iter = int(re.search(r"iter (\d+)/40", killed).group(1))
    assert 1 <= done_iter < 40

    res = _cli("--resume", "crash1", db=db)
    print(res.stdout)
    assert res.returncode == 0, res.stderr
    assert "continuing thread crash1" in res.stdout
    assert ("PAUSED at human gate" in res.stdout
            or "finished without a promotion candidate" in res.stdout)
    resumed = _list_line(db, "crash1")
    print(resumed)
    assert "iter 40/40" in resumed

    ref = _cli(*cfg, "--thread", "clean1", db=db)
    assert ref.returncode == 0, ref.stderr
    clean = _list_line(db, "clean1")
    print(clean)
    best = re.compile(r"best (\S+) (-?[\d.]+)")
    assert best.search(resumed).groups() == best.search(clean).groups()

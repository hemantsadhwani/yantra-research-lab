"""The research loop as a LangGraph ``StateGraph`` — checkpointed, resumable, human-gated.

This is the production-shaped expression of ``research_lab/supervisor.py``. The stdlib
supervisor stays the spec and the zero-dependency default; this module re-expresses the
same control flow as a graph so it gets, for free:

* **checkpointing** — every node boundary is persisted (SQLite by default), so a run can
  be inspected, listed and resumed from another process;
* **a real human gate** — ``gate`` calls ``interrupt()``, so the run *stops* until a
  human resumes it with ``Command(resume="approve" | "reject")``. Nothing is promoted by
  the loop itself.

Nodes are thin adapters over the existing agents (``Proposer``, ``Backtester``,
``Evaluator``) and the deterministic verification hooks — no agent logic is duplicated.
State is plain JSON (dicts/lists/scalars) so any checkpointer round-trips it without
custom serialisers.

    START → baseline → propose → backtest_all → record ─┬→ propose        (budget left)
                                                        ├→ gate → finalize (best is 'promote?')
                                                        └→ finalize        (nothing to promote)
    finalize → END

One deliberate difference from the stdlib loop: the proposer is rebuilt inside the
``propose`` node from checkpointed state (a live RNG cannot be checkpointed), and is
reseeded per iteration with ``hash((seed, iteration))``. Runs are fully deterministic,
but the variants differ from ``Supervisor(seed=...)`` for the same seed.

This module (and ``run_graph.py``) are the only places that import langgraph; the stdlib
path in ``supervisor.py`` / ``run.py`` never does.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from research_lab.agents import Evaluator, Proposer, make_backtester, score_result
from research_lab.memory import Memory
from research_lab.schemas import (
    BacktestResult,
    Evaluation,
    RankedVariant,
    RunResult,
    StrategyVariant,
    Trial,
)
from research_lab.verify import verify_result, verify_variant
from synthetic_engine import DEFAULT_STRATEGY, get_baseline

DEFAULT_CHECKPOINT_DB = ".yantra/checkpoints.sqlite"


class ResearchState(TypedDict, total=False):
    # config (set once by the caller)
    strategy: str
    seed: int
    iterations: int
    variants_per_iter: int
    use_llm: bool
    context_mode: str
    engine: str                    # "inprocess" | "mcp" (same contract, two transports)
    # progress
    iteration: int                 # completed iterations
    counter: int                   # last variant number issued (v001, v002, ...)
    baseline: dict[str, Any]       # BacktestResult as a dict
    baseline_score: float
    proposals: list[dict[str, Any]]    # this iteration's StrategyVariants
    ranked: list[dict[str, Any]]       # RankedVariant dicts, accumulated across iterations
    trials: list[dict[str, Any]]       # memory snapshot: Trial dicts, oldest first
    llm_calls: int                 # LLM accounting survives node-local proposers
    llm_failures: int              # a degraded run must never look like a clean one
    # human gate
    approval: str | None           # only ever set by a human resume
    promoted_id: str | None
    stop_reason: str


def initial_state(
    strategy: str = DEFAULT_STRATEGY,
    seed: int = 0,
    iterations: int = 4,
    variants_per_iter: int = 5,
    use_llm: bool = False,
    context_mode: str = "compacted",
    engine: str = "inprocess",
) -> ResearchState:
    return ResearchState(
        strategy=strategy, seed=seed, iterations=iterations,
        variants_per_iter=variants_per_iter, use_llm=use_llm, context_mode=context_mode,
        engine=engine,
        iteration=0, counter=0, proposals=[], ranked=[], trials=[],
        llm_calls=0, llm_failures=0, approval=None, promoted_id=None,
    )


# ------------------------------------------------------------------ conversions
def iteration_seed(seed: int, iteration: int) -> int:
    """Per-iteration proposer seed. ``hash`` of an int tuple is stable across processes
    (PYTHONHASHSEED only salts str/bytes), so checkpoint → resume stays deterministic."""
    return hash((seed, iteration)) & 0xFFFFFFFF


def memory_from_trials(trials: list[dict[str, Any]]) -> Memory:
    """Rebuild episodic memory by replaying ``observe`` over the checkpointed trial log."""
    memory = Memory()
    for t in trials:
        trial = Trial(**t)
        variant = StrategyVariant(id=trial.variant_id, params=dict(trial.params),
                                  rationale=trial.rationale)
        evaluation = Evaluation(variant_id=trial.variant_id, score=trial.score,
                                verdict=trial.verdict, beats_baseline=False)
        memory.observe(variant, evaluation)
    return memory


def ranked_variant(d: dict[str, Any]) -> RankedVariant:
    return RankedVariant(
        variant=StrategyVariant(**d["variant"]),
        result=BacktestResult(**d["result"]),
        evaluation=Evaluation(**d["evaluation"]),
    )


def best_ranked(ranked: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Highest score; ties go to the earliest, matching the stdlib loop's stable sort."""
    ordered = sorted(ranked, key=lambda d: d["evaluation"]["score"], reverse=True)
    return ordered[0] if ordered else None


def to_run_result(state: ResearchState) -> RunResult:
    """Render a (possibly paused) graph state with the same report as ``run.py``."""
    ranked = [ranked_variant(d) for d in state.get("ranked", [])]
    ranked.sort(key=lambda rv: rv.evaluation.score, reverse=True)
    return RunResult(
        iterations=state.get("iteration", 0),
        variants_tested=len(ranked),
        baseline=BacktestResult(**state["baseline"]),
        ranked=ranked,
    )


# ------------------------------------------------------------------------ nodes
def baseline_node(state: ResearchState) -> dict[str, Any]:
    strategy = state.get("strategy", DEFAULT_STRATEGY)
    variant = StrategyVariant(id="baseline", params=get_baseline(strategy),
                              rationale="baseline")
    verify_variant(variant)
    result = make_backtester(state.get("engine", "inprocess"), strategy).backtest(variant)
    verify_result(result, variant)      # the yardstick is checked too
    return {"baseline": asdict(result), "baseline_score": score_result(result)}


def propose_node(state: ResearchState) -> dict[str, Any]:
    memory = memory_from_trials(state.get("trials", []))
    proposer = Proposer(
        seed=iteration_seed(state.get("seed", 0), state.get("iteration", 0)),
        start_counter=state.get("counter", 0),
        use_llm=state.get("use_llm", False),
        context_mode=state.get("context_mode", "compacted"),
    )
    variants = proposer.propose(state["variants_per_iter"], memory)
    for v in variants:
        verify_variant(v)               # in-space before we spend a backtest
    return {
        "proposals": [asdict(v) for v in variants],
        "counter": proposer._counter,
        "llm_calls": state.get("llm_calls", 0) + proposer.llm_calls,
        "llm_failures": state.get("llm_failures", 0) + proposer.llm_failures,
    }


def backtest_all_node(state: ResearchState) -> dict[str, Any]:
    backtester = make_backtester(state.get("engine", "inprocess"),
                                 state.get("strategy", DEFAULT_STRATEGY))
    evaluator = Evaluator(baseline_score=state["baseline_score"])
    ranked = list(state.get("ranked", []))
    for d in state.get("proposals", []):
        variant = StrategyVariant(**d)
        result = backtester.backtest(variant)
        verify_result(result, variant)  # deterministic hook — fails loudly
        evaluation = evaluator.evaluate(variant, result)
        ranked.append(asdict(RankedVariant(variant, result, evaluation)))
    return {"ranked": ranked}


def record_node(state: ResearchState) -> dict[str, Any]:
    """The graph form of ``memory.observe``: append this iteration's trials."""
    n = len(state.get("proposals", []))
    ranked = state.get("ranked", [])
    this_iter = ranked[len(ranked) - n:] if n else []
    trials = list(state.get("trials", []))
    for d in this_iter:
        v, e = d["variant"], d["evaluation"]
        trials.append(asdict(Trial(variant_id=v["id"], params=dict(v["params"]),
                                   score=e["score"], verdict=e["verdict"],
                                   rationale=v["rationale"])))
    return {"trials": trials, "iteration": state.get("iteration", 0) + 1}


def gate_node(state: ResearchState) -> dict[str, Any]:
    # LangGraph re-runs this node from the top on resume: nothing above interrupt()
    # may have side effects. Computing ``best`` is pure.
    best = best_ranked(state.get("ranked", []))
    decision = interrupt({"best": best, "question": "promote?"})
    if isinstance(decision, str) and decision.strip().lower() == "approve":
        return {"approval": "approved", "promoted_id": best["variant"]["id"]}
    return {"approval": "rejected", "promoted_id": None}


def finalize_node(state: ResearchState) -> dict[str, Any]:
    ranked = sorted(state.get("ranked", []), key=lambda d: d["evaluation"]["score"],
                    reverse=True)
    return {"ranked": ranked, "stop_reason": state.get("stop_reason") or "iterations"}


def route_after_record(state: ResearchState) -> str:
    if state.get("iteration", 0) < state["iterations"]:
        return "propose"
    best = best_ranked(state.get("ranked", []))
    if best is not None and best["evaluation"]["verdict"] == "promote?":
        return "gate"
    return "finalize"


# ------------------------------------------------------------------ build / save
def default_checkpointer(path: str | os.PathLike[str] | None = None):
    """SQLite checkpointer at ``path`` / $RESEARCH_CHECKPOINT_DB / .yantra/checkpoints.sqlite."""
    from langgraph.checkpoint.sqlite import SqliteSaver

    db = Path(path or os.environ.get("RESEARCH_CHECKPOINT_DB") or DEFAULT_CHECKPOINT_DB)
    db.parent.mkdir(parents=True, exist_ok=True)
    saver = SqliteSaver(sqlite3.connect(str(db), check_same_thread=False))
    saver.setup()
    return saver


def build_graph(checkpointer=None):
    """Compile the research graph.

    ``checkpointer=None`` uses an in-memory saver: ``interrupt()`` needs *some*
    checkpointer, and an in-process run should still reach the human gate.
    """
    if checkpointer is None:
        from langgraph.checkpoint.memory import InMemorySaver
        checkpointer = InMemorySaver()

    g = StateGraph(ResearchState)
    g.add_node("baseline", baseline_node)
    g.add_node("propose", propose_node)
    g.add_node("backtest_all", backtest_all_node)
    g.add_node("record", record_node)
    g.add_node("gate", gate_node)
    g.add_node("finalize", finalize_node)

    g.add_edge(START, "baseline")
    g.add_edge("baseline", "propose")
    g.add_edge("propose", "backtest_all")
    g.add_edge("backtest_all", "record")
    g.add_conditional_edges("record", route_after_record, ["propose", "gate", "finalize"])
    g.add_edge("gate", "finalize")
    g.add_edge("finalize", END)
    return g.compile(checkpointer=checkpointer)

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

**Memory.** ``state["memory"]`` picks the store: ``"inmem"`` rebuilds ``Memory`` from the
checkpointed trial log in every ``propose`` (as before); ``"sqlite"`` opens a
``SqliteMemory`` on ``state["memory_db"]`` keyed by ``state["run_id"]``. ``record`` writes
each iteration's trials through to it, and ``finalize`` records a promotion *only* when a
human approved at the gate, then refreshes the materialised priors. Connections are
opened and closed inside each node — never stored in state — so state stays JSON.

This module (and ``run_graph.py``) are the only places that import langgraph; the stdlib
path in ``supervisor.py`` / ``run.py`` never does.
"""

from __future__ import annotations

import os
import sqlite3
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from research_lab.agents import Evaluator, Proposer, make_backtester, score_result
from research_lab.memory import Memory, MemoryLike
from research_lab.memory_store import SqliteMemory, default_memory_db
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
    provider: str | None           # llm_gateway provider name; None = $LLM_PROVIDER
    memory: str                    # "inmem" | "sqlite" (persistent, cross-run)
    memory_db: str | None          # SqliteMemory path when memory == "sqlite"
    run_id: str                    # this run's id in the memory store (defaults to thread)
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
    llm_cost_usd: float            # estimated (list price) across all LLM calls
    llm_structured_mode: str       # last successful gateway rung: native|json_schema|prompt|none
    llm_provider: str              # which provider/model actually answered (for the report)
    llm_model: str
    priors_used: int               # explorers drawn from learned priors (sqlite memory)
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
    provider: str | None = None,
    memory: str = "inmem",
    memory_db: str | None = None,
    run_id: str | None = None,
) -> ResearchState:
    if memory not in ("inmem", "sqlite"):
        raise ValueError(f"memory must be 'inmem' or 'sqlite', not {memory!r}")
    return ResearchState(
        strategy=strategy, seed=seed, iterations=iterations,
        variants_per_iter=variants_per_iter, use_llm=use_llm, context_mode=context_mode,
        engine=engine, provider=provider,
        memory=memory,
        memory_db=(memory_db or default_memory_db()) if memory == "sqlite" else None,
        run_id=run_id or f"{strategy}-s{seed}-{uuid.uuid4().hex[:8]}",
        priors_used=0,
        iteration=0, counter=0, proposals=[], ranked=[], trials=[],
        llm_calls=0, llm_failures=0, llm_cost_usd=0.0, llm_structured_mode="none",
        approval=None, promoted_id=None,
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


def open_memory(state: ResearchState) -> MemoryLike:
    """The memory store for this state. Callers close a ``SqliteMemory`` when done."""
    if state.get("memory", "inmem") == "sqlite":
        return SqliteMemory(state.get("memory_db") or default_memory_db(),
                            state.get("strategy", DEFAULT_STRATEGY), state["run_id"],
                            seed=state.get("seed"),
                            arm="llm" if state.get("use_llm") else "heuristic")
    return memory_from_trials(state.get("trials", []))


def _close(memory: MemoryLike) -> None:
    close = getattr(memory, "close", None)
    if callable(close):
        close()


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


def propose_node(state: ResearchState, provider: Any = None) -> dict[str, Any]:
    """``provider`` is an injected ``llm_gateway`` provider (tests); by default one is
    built from ``state["provider"]`` / ``$LLM_PROVIDER`` — only when ``use_llm`` is set."""
    use_llm = state.get("use_llm", False)
    if use_llm and provider is None:
        from llm_gateway import get_provider  # lazy: the heuristic graph never needs it
        provider = get_provider(state.get("provider"))
    proposer = Proposer(
        seed=iteration_seed(state.get("seed", 0), state.get("iteration", 0)),
        start_counter=state.get("counter", 0),
        use_llm=use_llm,
        context_mode=state.get("context_mode", "compacted"),
        provider=provider,
    )
    memory = open_memory(state)
    try:
        variants = proposer.propose(state["variants_per_iter"], memory)
    finally:
        _close(memory)
    for v in variants:
        verify_variant(v)               # in-space before we spend a backtest
    update: dict[str, Any] = {
        "proposals": [asdict(v) for v in variants],
        "counter": proposer._counter,
        "llm_calls": state.get("llm_calls", 0) + proposer.llm_calls,
        "llm_failures": state.get("llm_failures", 0) + proposer.llm_failures,
        "llm_cost_usd": state.get("llm_cost_usd", 0.0) + proposer.llm_cost_usd,
        "priors_used": state.get("priors_used", 0) + proposer.used_priors,
    }
    if use_llm:
        update["llm_provider"] = proposer.provider_name
        update["llm_model"] = proposer.model
        if proposer.llm_calls and proposer.llm_failures == 0:
            update["llm_structured_mode"] = proposer.llm_structured_mode
    return update


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
    """The graph form of ``memory.observe``: append this iteration's trials (and, with
    sqlite memory, write them through to the store — idempotent per variant id)."""
    n = len(state.get("proposals", []))
    ranked = state.get("ranked", [])
    this_iter = ranked[len(ranked) - n:] if n else []
    trials = list(state.get("trials", []))
    for d in this_iter:
        v, e = d["variant"], d["evaluation"]
        trials.append(asdict(Trial(variant_id=v["id"], params=dict(v["params"]),
                                   score=e["score"], verdict=e["verdict"],
                                   rationale=v["rationale"])))
    if state.get("memory") == "sqlite" and this_iter:
        mem = open_memory(state)
        try:
            for d in this_iter:
                mem.observe(StrategyVariant(**d["variant"]), Evaluation(**d["evaluation"]))
        finally:
            _close(mem)
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
    if state.get("memory") == "sqlite":
        mem = open_memory(state)
        try:
            # ``approval`` is only ever set by a human resume of the gate.
            if state.get("approval") == "approved" and state.get("promoted_id"):
                mem.record_promotion(state["promoted_id"], decided_by="human")
            mem.refresh_priors()
        finally:
            _close(mem)
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


def build_graph(checkpointer=None, provider: Any = None):
    """Compile the research graph.

    ``checkpointer=None`` uses an in-memory saver: ``interrupt()`` needs *some*
    checkpointer, and an in-process run should still reach the human gate.
    ``provider`` injects an ``llm_gateway`` provider object into every ``propose``
    step (used by tests with a ``FakeProvider``; it is not checkpointed).
    """
    if checkpointer is None:
        from langgraph.checkpoint.memory import InMemorySaver
        checkpointer = InMemorySaver()

    g = StateGraph(ResearchState)
    g.add_node("baseline", baseline_node)
    if provider is None:
        g.add_node("propose", propose_node)
    else:
        def propose_with_provider(state: ResearchState) -> dict[str, Any]:
            return propose_node(state, provider=provider)
        g.add_node("propose", propose_with_provider)
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

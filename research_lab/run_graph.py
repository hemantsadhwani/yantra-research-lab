"""CLI for the LangGraph research loop — checkpointed, pausable at a real human gate.

    python -m research_lab.run_graph --iterations 5 --variants 6 --seed 3
    python -m research_lab.run_graph --resume <thread> --decision approve
    python -m research_lab.run_graph --list
    python -m research_lab.run_graph --engine mcp      # backtests over MCP stdio (needs .[mcp])
    python -m research_lab.run_graph --memory sqlite   # persistent memory; learns from past runs
    python -m research_lab.run_graph --judge           # LLM judge may veto 'promote?' before the gate

A fresh run executes until the human gate, prints the ranked table, and stops with the
exact command to resume it. The pause is persisted in SQLite, so the resume can happen
from another shell, another process, or tomorrow. Needs the ``agents`` extra
(``pip install -e '.[agents]'``); the stdlib ``python -m research_lab.run`` does not.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from langgraph.types import Command

from research_lab import observability
from research_lab.agents.backtester import close_mcp_clients
from research_lab.agents.context import CONSTRUCTIONS
from research_lab.agents.judge import footer as judge_footer
from research_lab.agents.judge import veto_line
from research_lab.graph import (
    DEFAULT_CHECKPOINT_DB,
    best_ranked,
    budget_from_state,
    build_graph,
    default_checkpointer,
    initial_state,
    to_run_result,
)
from research_lab.memory_store import SqliteMemory, default_memory_db
from research_lab.run import MCP_ENGINE_LABEL, memory_label, render_report
from synthetic_engine import DEFAULT_STRATEGY, list_strategies


def _db_path(arg: str | None) -> str:
    return arg or os.environ.get("RESEARCH_CHECKPOINT_DB") or DEFAULT_CHECKPOINT_DB


def _cfg(thread: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread}}


def _stream(graph, payload, cfg) -> bool:
    """Run to the next stop, logging progress. Returns True if paused at the gate."""
    paused = False
    for chunk in graph.stream(payload, cfg, stream_mode="updates"):
        for node, update in chunk.items():
            if node == "__interrupt__":
                paused = True
            elif node == "propose" and update.get("stop_reason") == "budget":
                b = update["budget"]
                print(f"  · budget exhausted before iter {update.get('budget_exhausted_at_iteration', '?')}"
                      f" (${b['spent_usd']:.4f} spent, {b['llm_calls']} llm calls): "
                      f"heuristic batch, then stop")
            elif node == "baseline":
                b = update["baseline"]
                print(f"  · baseline: return {b['total_return_pct']:+.1f}% · "
                      f"score {update['baseline_score']:.1f} · {b['trades']} trades")
            elif node == "record":
                state = graph.get_state(cfg).values
                best = max(t["score"] for t in update["trials"])
                print(f"  · iter {update['iteration']}/{state['iterations']}: "
                      f"best score so far {best:.1f}")
    return paused


def _print_llm(state: dict[str, Any]) -> None:
    if state.get("use_llm"):
        fails = state.get("llm_failures", 0)
        who = f"{state.get('llm_provider', state.get('provider') or '?')}/" \
              f"{state.get('llm_model', '?')}"
        print(f"  proposer: {who} · structured={state.get('llm_structured_mode', 'none')} · "
              f"{state.get('llm_calls', 0) - state.get('judge_calls', 0)} calls · "
              f"${state.get('llm_cost_usd', 0.0) - state.get('judge_cost_usd', 0.0):.4f} · "
              f"context '{state.get('context_mode')}'"
              + (f" · llm_failures={fails} (fell back to the heuristic)" if fails else ""))
        print()


def _print_judge(state: dict[str, Any]) -> None:
    """One line per veto, then ``judge: <calls> calls · <vetoes> vetoes · <n> abstained``."""
    if not state.get("judge"):
        return
    for entry in state.get("judge_log", []):
        print(f"  {veto_line(entry['variant_id'], entry['verdict'])}")
    print("  " + judge_footer(state.get("judge_calls", 0), state.get("judge_vetoes", 0),
                              state.get("judge_failures", 0), state.get("judge_error")))


def budget_footer(state: dict[str, Any]) -> str:
    """``budget: $0.0000/∞ · llm calls 0/∞ · stopped: iterations``."""
    return budget_from_state(state).footer(state.get("stop_reason"))


def _beats_baseline(state: dict[str, Any]) -> bool:
    best = best_ranked(state.get("ranked", []))
    return best is not None and best["evaluation"]["score"] > state["baseline_score"]


def _ask_tty() -> str | None:
    """Interactive gate for a human at a terminal. Empty answer = pause and resume later."""
    try:
        ans = input("  promote? [approve / reject / Enter to pause]: ").strip().lower()
    except EOFError:
        return None
    return ans if ans in {"approve", "reject"} else None


def _print_decision(state: dict[str, Any], db: str) -> None:
    if state.get("approval") == "approved":
        print(f"  APPROVED {state['promoted_id']} · promoted (human)")
        if state.get("memory") == "sqlite":
            print(f"  promotion recorded in {state.get('memory_db')}")
    else:
        print("  REJECTED · nothing promoted")
    print(f"  checkpoint: {db}")


def _list(graph, saver, db: str) -> int:
    threads: list[str] = []
    for tup in saver.list(None):
        t = tup.config["configurable"]["thread_id"]
        if t not in threads:
            threads.append(t)          # newest checkpoint first
    if not threads:
        print(f"  no threads in {db}")
        return 0
    print(f"  threads in {db}:")
    for t in threads:
        snap = graph.get_state(_cfg(t))
        v = snap.values
        best = best_ranked(v.get("ranked", []))
        best_s = (f"best {best['variant']['id']} {best['evaluation']['score']:.1f}"
                  if best else "best -")
        status = ("PAUSED at gate" if snap.next == ("gate",)
                  else f"next {snap.next}" if snap.next
                  else f"done · {v.get('approval') or v.get('stop_reason', '')}")
        print(f"  {t:<44} {v.get('strategy', '?')} s{v.get('seed', '?')} · "
              f"iter {v.get('iteration', 0)}/{v.get('iterations', '?')} · {best_s} · {status}")
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    finally:
        close_mcp_clients()    # no-op unless --engine mcp started a server


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run the research loop as a checkpointed graph.")
    ap.add_argument("--iterations", type=int, default=4)
    ap.add_argument("--variants", type=int, default=5)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--strategy", default=DEFAULT_STRATEGY, choices=list_strategies())
    ap.add_argument("--use-llm", action="store_true",
                    help="propose with an LLM via llm_gateway (needs the llm extra and "
                         "the chosen provider's credentials)")
    ap.add_argument("--provider", choices=["anthropic", "bedrock", "ollama"],
                    default=os.environ.get("LLM_PROVIDER") or None,
                    help="LLM provider for --use-llm (default: $LLM_PROVIDER or anthropic)")
    ap.add_argument("--context-mode", default="compacted", choices=list(CONSTRUCTIONS))
    ap.add_argument("--engine", default="inprocess", choices=["inprocess", "mcp"],
                    help="call the engine in-process (default) or over MCP stdio via "
                         "python -m mcp_server.server (needs the mcp extra)")
    ap.add_argument("--memory", default="inmem", choices=["inmem", "sqlite"],
                    help="rebuild memory from the checkpoint (default) or use a persistent "
                         "SQLite store that learns priors from previous runs")
    ap.add_argument("--db-memory", metavar="PATH",
                    help="SQLite memory path (default: $RESEARCH_MEMORY_DB or "
                         ".yantra/research.sqlite)")
    ap.add_argument("--thread", help="thread id (default: <strategy>-s<seed>-<UTC timestamp>)")
    ap.add_argument("--db", help=f"checkpoint sqlite path (default: $RESEARCH_CHECKPOINT_DB "
                                 f"or {DEFAULT_CHECKPOINT_DB})")
    ap.add_argument("--resume", metavar="THREAD", help="resume a thread paused at the gate")
    ap.add_argument("--decision", choices=["approve", "reject"], help="with --resume")
    ap.add_argument("--list", action="store_true", help="list checkpointed threads")
    ap.add_argument("--max-usd", type=float, default=None,
                    help="stop the loop once estimated LLM spend reaches this many USD "
                         "(checked before each call; default: unbounded)")
    ap.add_argument("--max-llm-calls", type=int, default=None,
                    help="stop the loop once this many LLM calls have been made "
                         "(default: unbounded)")
    ap.add_argument("--judge", action="store_true",
                    help="before the human gate, an LLM judge reviews the top-3 'promote?' "
                         "candidates and may downgrade them to 'hold' (never upgrade); if all "
                         "are vetoed the run finishes without pausing. Uses --provider / "
                         "$LLM_PROVIDER; no key → it abstains.")
    ap.add_argument("--no-gate", action="store_true",
                    help="never prompt: stop at the gate and exit 0 (for CI)")
    ap.add_argument("--assert-beats-baseline", action="store_true",
                    help="exit 1 unless the best variant beats the baseline score")
    args = ap.parse_args(argv)

    observability.configure()      # no LOGFIRE_TOKEN → no-op, nothing leaves the process
    db = _db_path(args.db)
    saver = default_checkpointer(db)
    graph = build_graph(saver)

    if args.list:
        return _list(graph, saver, db)

    if args.resume:
        if not args.decision:
            ap.error("--resume needs --decision approve|reject")
        cfg = _cfg(args.resume)
        snap = graph.get_state(cfg)
        if snap.next != ("gate",):
            print(f"  thread {args.resume!r} is not paused at the human gate in {db}",
                  file=sys.stderr)
            return 2
        with observability.span("research_resume", thread_id=args.resume,
                                decision=args.decision):
            _stream(graph, Command(resume=args.decision), cfg)
        state = graph.get_state(cfg).values
        _print_decision(state, db)
        _print_judge(state)
        print(f"  {budget_footer(state)}")
        if args.assert_beats_baseline and not _beats_baseline(state):
            return 1
        return 0

    if args.use_llm or args.judge:
        try:
            from load_env import load_env
            load_env()
        except ImportError:
            pass
        if args.provider:
            os.environ["LLM_PROVIDER"] = args.provider

    thread = args.thread or (
        f"{args.strategy}-s{args.seed}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    )
    cfg = _cfg(thread)
    if graph.get_state(cfg).values:
        print(f"  thread {thread!r} already exists in {db}; pass a new --thread "
              f"or --resume it", file=sys.stderr)
        return 2

    db_memory = (args.db_memory or default_memory_db()) if args.memory == "sqlite" else None
    memory_line = memory_label("inmem")
    if db_memory:
        # Count before the run writes anything: this run is excluded either way.
        with SqliteMemory(db_memory, args.strategy, run_id=thread, seed=args.seed,
                          arm="llm" if args.use_llm else "heuristic") as m:
            memory_line = memory_label("sqlite", db_memory, m.prior_run_count())

    if args.engine == "mcp":
        print(f"  · {MCP_ENGINE_LABEL}")
    provider = args.provider if (args.use_llm or args.judge) else None
    with observability.span("research_run", thread_id=thread, strategy=args.strategy,
                            seed=args.seed, engine=args.engine,
                            provider=(provider or os.environ.get("LLM_PROVIDER")
                                      or "anthropic") if args.use_llm else "heuristic",
                            iterations=args.iterations, variants=args.variants,
                            max_usd=args.max_usd, max_llm_calls=args.max_llm_calls) as run_span:
        paused = _stream(graph, initial_state(
            strategy=args.strategy, seed=args.seed, iterations=args.iterations,
            variants_per_iter=args.variants, use_llm=args.use_llm,
            context_mode=args.context_mode, engine=args.engine,
            provider=provider,
            memory=args.memory, memory_db=db_memory, run_id=thread,
            max_usd=args.max_usd, max_llm_calls=args.max_llm_calls,
            judge=args.judge,
        ), cfg)
        state = graph.get_state(cfg).values
        observability.set_attributes(run_span, {
            "iterations_completed": state.get("iteration", 0),
            "llm_calls": state.get("llm_calls", 0),
            "llm_cost_usd": state.get("llm_cost_usd", 0.0),
            "stop_reason": state.get("stop_reason") or "iterations",
            "paused_at_gate": paused,
        })
    print(render_report(to_run_result(state), args.strategy, engine=args.engine,
                        memory=memory_line))
    _print_llm(state)
    _print_judge(state)
    print(f"  {budget_footer(state)}")
    print()

    if paused:
        decision = None
        if not args.no_gate and sys.stdin.isatty():
            decision = _ask_tty()
        if decision:
            _stream(graph, Command(resume=decision), cfg)
            _print_decision(graph.get_state(cfg).values, db)
        else:
            print(f"  PAUSED at human gate · thread {thread}")
            db_flag = f" --db {args.db}" if args.db else ""
            print(f"  resume: python -m research_lab.run_graph --resume {thread} "
                  f"--decision approve{db_flag}   (or --decision reject)")
            print(f"  checkpoint: {db}")
    else:
        print(f"  finished without a promotion candidate · thread {thread}")

    if args.assert_beats_baseline and not _beats_baseline(state):
        print("  ASSERT FAILED · best variant does not beat the baseline", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

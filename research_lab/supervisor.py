"""Supervisor — the bounded autonomous research loop.

plan -> propose N variants -> backtest each -> judge vs baseline -> rank -> remember
the best -> iterate, until the iteration budget is spent. Nothing is promoted
autonomously: the top variant is surfaced with a 'promote?' verdict for a human gate.

This is deliberately a *workflow-shaped* loop (predictable control flow) with agentic
steps inside — the production build re-expresses it as a LangGraph StateGraph so it gets
checkpointing, streaming and HITL interrupts for free. The control logic here is the spec.

``use_llm`` swaps the proposer for a Claude call without changing a line below: the
verification hooks, the evaluator, memory and the human gate all sit behind the same
typed contracts either way. That is ADR-0003's claim made demonstrable — the loop is
the spec, and what runs inside a step is an implementation detail.

``judge`` (optional, duck-typed: anything with ``.review(ranked, baseline, summary)``, i.e.
``research_lab.agents.judge.Judge``) runs once after the loop on the top-k ``promote?``
results. It can only veto (``promote?`` → ``hold``); it is passed in, never imported here,
so the default path stays stdlib-only.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from research_lab.agents import Backtester, Evaluator, Proposer, score_result
from research_lab.budget import Budget
from research_lab.memory import Memory, MemoryLike
from research_lab.schemas import (
    RankedVariant,
    RunResult,
    StrategyVariant,
)
from research_lab.verify import verify_result, verify_variant
from synthetic_engine import DEFAULT_STRATEGY, get_baseline


class Supervisor:
    def __init__(
        self,
        seed: int = 0,
        strategy: str = DEFAULT_STRATEGY,
        log: Callable[[str], None] | None = None,
        use_llm: bool = False,
        context_mode: str = "compacted",
        backtester: Backtester | None = None,
        memory: MemoryLike | None = None,
        budget: Budget | None = None,
        proposer: Proposer | None = None,
        judge: Any = None,
    ) -> None:
        self.strategy = strategy
        # The only line the LLM swap touches. Everything below — verification, the
        # evaluator, memory, the HITL gate — is indifferent to which proposer ran.
        # ``proposer`` is injectable (tests pass one wired to a FakeProvider).
        self.proposer = proposer if proposer is not None else Proposer(
            seed=seed, use_llm=use_llm, context_mode=context_mode)
        # One Budget instance for the whole run; the proposer checks and charges it.
        self.budget = budget
        if budget is not None:
            self.proposer.budget = budget
        self.stop_reason: str | None = None
        # Injectable (e.g. an MCPBacktester); anything with ``.backtest(variant)`` works.
        self.backtester = backtester if backtester is not None else Backtester(strategy=strategy)
        # In-process by default; pass a SqliteMemory to learn across runs.
        self.memory: MemoryLike = memory if memory is not None else Memory()
        self._log = log or (lambda _msg: None)
        # Optional veto-only LLM judge; shares the run's budget unless it brought its own.
        self.judge = judge
        if judge is not None and budget is not None and getattr(judge, "budget", None) is None:
            judge.budget = budget

    def run(self, iterations: int = 4, variants_per_iter: int = 5) -> RunResult:
        # Baseline first — every variant is judged against it (offline↔online parity).
        baseline_variant = StrategyVariant(
            id="baseline", params=get_baseline(self.strategy), rationale="baseline"
        )
        verify_variant(baseline_variant)
        baseline = self.backtester.backtest(baseline_variant)
        verify_result(baseline, baseline_variant)   # the yardstick is checked too
        evaluator = Evaluator(baseline_score=score_result(baseline))
        self._log(f"baseline: return {baseline.total_return_pct:+.1f}% · "
                  f"score {evaluator.baseline_score:.1f} · {baseline.trades} trades")

        ranked: list[RankedVariant] = []
        completed = 0
        self.stop_reason = "iterations"
        for it in range(1, iterations + 1):
            for variant in self.proposer.propose(variants_per_iter, self.memory):
                verify_variant(variant)                 # in-space before we spend a backtest
                result = self.backtester.backtest(variant)
                verify_result(result, variant)          # deterministic hook — fails loudly
                evaluation = evaluator.evaluate(variant, result)
                self.memory.observe(variant, evaluation)
                ranked.append(RankedVariant(variant, result, evaluation))
            self._log(f"iter {it}/{iterations}: best score so far {self.memory.best_score():.1f}")
            completed = it
            if self.proposer.budget_exhausted:
                # The batch that found the budget spent ran on the heuristic; stop here.
                self.stop_reason = "budget"
                self._log(f"budget exhausted at iter {it}: stopping early")
                break

        ranked.sort(key=lambda rv: rv.evaluation.score, reverse=True)
        if self.judge is not None:
            n_promote = sum(rv.evaluation.verdict == "promote?" for rv in ranked)
            summary = (f"{len(ranked)} variants tested over {completed} iterations; baseline "
                       f"score {evaluator.baseline_score:.1f}; {n_promote} reached 'promote?'.")
            ranked = self.judge.review(ranked, baseline, summary)   # order is preserved
        return RunResult(
            iterations=completed,
            variants_tested=len(ranked),
            baseline=baseline,
            ranked=ranked,
        )

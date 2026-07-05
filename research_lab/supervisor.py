"""Supervisor — the bounded autonomous research loop.

plan -> propose N variants -> backtest each -> judge vs baseline -> rank -> remember
the best -> iterate, until the iteration budget is spent. Nothing is promoted
autonomously: the top variant is surfaced with a 'promote?' verdict for a human gate.

This is deliberately a *workflow-shaped* loop (predictable control flow) with agentic
steps inside — the production build re-expresses it as a LangGraph StateGraph so it gets
checkpointing, streaming and HITL interrupts for free. The control logic here is the spec.
"""

from __future__ import annotations

from typing import Callable, Optional

from research_lab.agents import Backtester, Evaluator, Proposer, score_result
from research_lab.memory import Memory
from research_lab.schemas import (
    BacktestResult,
    RankedVariant,
    RunResult,
    StrategyVariant,
)
from synthetic_engine import DEFAULT_STRATEGY, get_baseline


class Supervisor:
    def __init__(
        self,
        seed: int = 0,
        strategy: str = DEFAULT_STRATEGY,
        log: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.strategy = strategy
        self.proposer = Proposer(seed=seed)
        self.backtester = Backtester(strategy=strategy)
        self.memory = Memory()
        self._log = log or (lambda _msg: None)

    def run(self, iterations: int = 4, variants_per_iter: int = 5) -> RunResult:
        # Baseline first — every variant is judged against it (offline↔online parity).
        baseline = self.backtester.backtest(
            StrategyVariant(id="baseline", params=get_baseline(self.strategy), rationale="baseline")
        )
        evaluator = Evaluator(baseline_score=score_result(baseline))
        self._log(f"baseline: return {baseline.total_return_pct:+.1f}% · "
                  f"score {evaluator.baseline_score:.1f} · {baseline.trades} trades")

        ranked: list[RankedVariant] = []
        for it in range(1, iterations + 1):
            for variant in self.proposer.propose(variants_per_iter, self.memory):
                result = self.backtester.backtest(variant)
                evaluation = evaluator.evaluate(variant, result)
                self.memory.observe(variant, evaluation)
                ranked.append(RankedVariant(variant, result, evaluation))
            self._log(f"iter {it}/{iterations}: best score so far {self.memory.best_score():.1f}")

        ranked.sort(key=lambda rv: rv.evaluation.score, reverse=True)
        return RunResult(
            iterations=iterations,
            variants_tested=len(ranked),
            baseline=baseline,
            ranked=ranked,
        )

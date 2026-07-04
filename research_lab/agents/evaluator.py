"""Evaluator agent — scores a backtest on risk-adjusted terms and judges it vs the baseline.

Tier-1 uses a transparent risk-adjusted score. The production build adds an
**LLM-as-judge** rubric on top (does the rationale hold? is the edge plausible or
overfit?) and a regression eval set gated in CI. See ADR-0003.
"""

from __future__ import annotations

from research_lab.schemas import BacktestResult, Evaluation, StrategyVariant

PROMOTE_MARGIN = 10.0   # points a variant must beat the baseline by to be promotion-eligible
MIN_TRADES = 5          # avoid promoting a variant that barely traded (statistical guardrail)


def score_result(r: BacktestResult) -> float:
    """Reward return, penalise drawdown, reward a win-rate edge over 50%."""
    return r.total_return_pct - 0.5 * r.max_drawdown_pct + 40.0 * (r.win_rate - 0.5)


class Evaluator:
    def __init__(self, baseline_score: float) -> None:
        self.baseline_score = baseline_score

    def evaluate(self, variant: StrategyVariant, result: BacktestResult) -> Evaluation:
        s = score_result(result)
        beats = s > self.baseline_score
        if s >= self.baseline_score + PROMOTE_MARGIN and result.trades >= MIN_TRADES:
            verdict = "promote?"     # note the '?': promotion needs human approval (HITL)
        elif beats:
            verdict = "hold"
        else:
            verdict = "reject"
        return Evaluation(
            variant_id=variant.id,
            score=round(s, 2),
            verdict=verdict,
            beats_baseline=beats,
            notes=f"score {s:.1f} vs baseline {self.baseline_score:.1f}",
        )

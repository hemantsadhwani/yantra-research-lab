"""Deterministic verification hooks — the loop's ground truth.

An agent loop that cannot check its own work compounds errors: every bad step
becomes the input to the next one. These checks give the loop *ground truth*
rather than the model's opinion, and they are deliberately **loud**: a violation
raises rather than returning a degraded result.

Why loud matters here. The nastiest failure in this loop is silent, not fatal.
A NaN metric propagates cleanly — every comparison against NaN is False, so a
NaN-scored variant simply never beats the baseline. The run completes, the table
renders, the numbers look plausible, and the loop has learned nothing. Nobody
finds out. A raised exception at the boundary turns that into a build failure.

These are deterministic checks, not a model judging a model. Per the verification
ladder: use a deterministic check wherever one exists, and reserve LLM-as-judge
for things with no ground truth.
"""

from __future__ import annotations

import math

from research_lab.schemas import BacktestResult, StrategyVariant
from synthetic_engine import PARAM_SPACE


class VerificationError(AssertionError):
    """A backtest result or variant violated an invariant. Fail the run."""


def _finite(name: str, value: float, ctx: str) -> None:
    if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise VerificationError(
            f"{ctx}: {name} is not a finite number (got {value!r}). "
            "NaN/inf compares False against everything and would fail silently."
        )


def verify_variant(variant: StrategyVariant) -> None:
    """Every proposed variant must sit inside the declared parameter space."""
    ctx = f"variant {variant.id}"
    missing = set(PARAM_SPACE) - set(variant.params)
    extra = set(variant.params) - set(PARAM_SPACE)
    if missing or extra:
        raise VerificationError(
            f"{ctx}: parameter keys do not match the space "
            f"(missing={sorted(missing)}, unexpected={sorted(extra)})"
        )
    for key, (lo, hi) in PARAM_SPACE.items():
        val = variant.params[key]
        _finite(key, val, ctx)
        if not (lo <= val <= hi):
            raise VerificationError(
                f"{ctx}: {key}={val} is outside the declared range [{lo}, {hi}]"
            )


def verify_result(result: BacktestResult, variant: StrategyVariant) -> None:
    """Every backtest result must be internally consistent before it is scored."""
    ctx = f"result for {variant.id}"

    # 1. Identity — catches a stale or mismatched result being scored as this one.
    if result.variant_id != variant.id:
        raise VerificationError(
            f"{ctx}: result belongs to {result.variant_id!r}, not {variant.id!r}. "
            "A mismatched result would score the wrong variant."
        )

    # 2. Finiteness — the silent killer.
    for name in ("total_return_pct", "win_rate", "max_drawdown_pct", "sharpe"):
        _finite(name, getattr(result, name), ctx)

    # 3. Bounds — a win rate is a proportion; a drawdown is a magnitude.
    if not (0.0 <= result.win_rate <= 1.0):
        raise VerificationError(f"{ctx}: win_rate={result.win_rate} is not in [0, 1]")
    if result.max_drawdown_pct < 0:
        raise VerificationError(
            f"{ctx}: max_drawdown_pct={result.max_drawdown_pct} is negative; "
            "drawdown is reported as a positive magnitude"
        )
    if result.trades < 0:
        raise VerificationError(f"{ctx}: trades={result.trades} is negative")

    # 4. Coherence — no trades cannot produce a return or a win rate.
    if result.trades == 0 and (result.total_return_pct != 0 or result.win_rate != 0):
        raise VerificationError(
            f"{ctx}: 0 trades but total_return_pct={result.total_return_pct} "
            f"and win_rate={result.win_rate}. One of these is wrong."
        )

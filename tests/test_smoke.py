"""Tier-1 smoke tests: the engine is deterministic, the loop runs and beats the baseline,
and nothing is promoted without a human gate."""

from research_lab.agents.evaluator import score_result
from research_lab.supervisor import Supervisor
from synthetic_engine import (
    BASELINE_PARAMS,
    DEFAULT_STRATEGY,
    get_baseline,
    list_strategies,
    run_backtest,
)


def test_engine_is_deterministic():
    # Same inputs -> identical output. This is the offline/online parity guarantee.
    assert run_backtest(BASELINE_PARAMS) == run_backtest(BASELINE_PARAMS)


def test_default_strategy_is_byte_identical():
    # The multi-strategy refactor must not move the original single-strategy surface.
    assert run_backtest(BASELINE_PARAMS) == run_backtest(BASELINE_PARAMS, strategy=DEFAULT_STRATEGY)


def test_named_strategies_are_distinct_but_share_the_contract():
    # Real products (by name) are synthetic stand-ins here: same contract, different surface.
    names = list_strategies()
    assert {"nifty-weekday", "nifty-expiry", "sensex-expiry"} <= set(names)
    surfaces = {s: run_backtest(get_baseline(s), strategy=s)["total_return_pct"] for s in names}
    assert len(set(surfaces.values())) == len(names)  # each engine is genuinely different


def test_loop_drives_any_named_strategy():
    # The same agent loop drives a named strategy exactly like the default one.
    run = Supervisor(seed=3, strategy="nifty-expiry").run(iterations=3, variants_per_iter=5)
    assert run.best is not None
    assert run.best.evaluation.score > score_result(run.baseline)


def test_unknown_strategy_is_rejected():
    try:
        run_backtest(BASELINE_PARAMS, strategy="does-not-exist")
    except ValueError:
        return
    raise AssertionError("unknown strategy should raise ValueError")


def test_loop_runs_and_discovers_a_winner():
    run = Supervisor(seed=3).run(iterations=5, variants_per_iter=6)
    assert run.variants_tested == 30
    assert run.best is not None
    assert run.best.evaluation.score > score_result(run.baseline)
    assert run.best.evaluation.verdict == "promote?"


def test_no_autonomous_promotion():
    # verdicts are only ever a question ('promote?') or hold/reject — never 'promoted'.
    run = Supervisor(seed=1).run(iterations=3, variants_per_iter=5)
    assert all(rv.evaluation.verdict in {"promote?", "hold", "reject"} for rv in run.ranked)

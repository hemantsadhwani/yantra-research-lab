"""Tier-1 smoke tests: the engine is deterministic, the loop runs and beats the baseline,
and nothing is promoted without a human gate."""

from research_lab.agents.evaluator import score_result
from research_lab.supervisor import Supervisor
from synthetic_engine import BASELINE_PARAMS, run_backtest


def test_engine_is_deterministic():
    # Same inputs -> identical output. This is the offline/online parity guarantee.
    assert run_backtest(BASELINE_PARAMS) == run_backtest(BASELINE_PARAMS)


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

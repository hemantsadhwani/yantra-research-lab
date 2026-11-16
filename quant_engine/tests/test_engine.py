"""The public engine: causality (no look-ahead), fill/cost accounting, data checks, the
validation protocol's shape, and deterministic synthetic markets."""

from __future__ import annotations

import pytest

from quant_engine import backtest as bt
from quant_engine import indicators as ind
from quant_engine import synthetic
from quant_engine import validate as v
from quant_engine.data import Bars, dataset_card, from_csv
from quant_engine.templates import TEMPLATES, positions

MARKET = synthetic.generate("meanrev", 7, n=900)


def sample_params(name: str) -> list[dict]:
    """A few parameter sets per template, filters on and off."""
    space = TEMPLATES[name].space
    first = {k: vals[0] for k, vals in space.items()}
    last = {k: vals[-1] for k, vals in space.items()}
    return [first, {**last, "trend_ema": 100, "vix_max": 25, "atr_stop": 2.0}]


@pytest.mark.parametrize("name", sorted(TEMPLATES))
def test_no_lookahead_signals_never_change_when_the_future_is_removed(name: str) -> None:
    for params in sample_params(name):
        full = positions(MARKET, name, params)
        for cut in (150, 333, 600, 899):
            past_only = positions(MARKET.slice(0, cut + 1), name, params)
            assert past_only == full[: cut + 1], (name, params, cut)


def test_indicators_are_causal_and_correct_on_a_simple_series() -> None:
    x = [float(i) for i in range(1, 21)]
    assert ind.sma(x, 3)[2] == 2.0 and ind.sma(x, 3)[1] is None
    assert ind.prior_max(x, 3)[5] == 5.0          # max of bars 2..4 (values 3,4,5), not bar 5
    assert ind.prior_min(x, 3)[5] == 3.0
    assert ind.rsi(x, 5)[10] == 100.0              # only gains
    e = ind.ema(x, 4)
    assert e[3] == pytest.approx(2.5) and e[4] == pytest.approx(0.4 * 5 + 0.6 * 2.5)


def test_fills_at_next_open_and_costs_on_every_change() -> None:
    b = Bars(["d0", "d1", "d2", "d3"], open=[100, 110, 121, 100], high=[200] * 4, low=[1] * 4,
             close=[100, 120, 110, 100])
    res = bt.run(b, [1, 1, 0, 0], cost_bps=10)
    # long decided at d0 close -> bought at d1 open 110; d1 earns open->close, minus cost
    assert res.returns[1] == pytest.approx(120 / 110 - 1 - 0.001)
    # still long at d1 close -> d2 earns the overnight gap and the whole day
    assert res.returns[2] == pytest.approx((121 / 120 - 1) + (110 / 121 - 1))
    # flat decided at d2 close -> sold at d3 open: d3 earns only the gap, minus cost
    assert res.returns[3] == pytest.approx(100 / 110 - 1 - 0.001)
    assert res.trades == [(1, 3, pytest.approx(100 / 110 - 1 - 0.002))]


def test_metrics_drawdown_and_sharpe() -> None:
    res = bt.Result([0.0, 0.1, -0.5, 0.2], [])
    m = bt.metrics(res, 0, 4)
    assert m["max_drawdown_pct"] == 50.0 and m["days"] == 4
    assert bt.sharpe([0.01] * 10) == 0.0


def test_dataset_card_reports_problems_and_hashes() -> None:
    card = dataset_card(MARKET, "synthetic meanrev seed 7")
    assert card["passed"] and card["rows"] == 900 and len(card["sha256"]) == 16
    bad = from_csv("date,open,high,low,close,vix\n2020-01-02,10,9,8,10,\n2020-01-02,10,11,9,10,\n")
    c = dataset_card(bad, "bad")
    assert not c["passed"] and c["checks"]["bad_ohlc"] == 1 and c["checks"]["duplicate_dates"] == 1
    assert from_csv(MARKET.to_csv()).close == pytest.approx(MARKET.close)


def test_synthetic_markets_are_deterministic_and_distinct() -> None:
    a, b = synthetic.generate("trend", 3, n=300), synthetic.generate("trend", 3, n=300)
    assert a.close == b.close and a.vix == b.vix
    assert synthetic.generate("noise", 3, n=300).close != a.close
    with pytest.raises(ValueError):
        synthetic.generate("magic", 1)


def test_protocol_shape_and_the_holdout_is_only_read_after_walk_forward_passes() -> None:
    b = synthetic.generate("noise", 11, n=1500)
    proto = v.Protocol(holdout_days=300, folds=4)
    cands = v.evaluate_all(b, "ema_cross", v.grid("ema_cross", with_filters=False), proto.cost_bps)
    out = v.protocol(b, cands, proto)
    assert out["trials"] == 16 and len(out["walk_forward"]["folds"]) == 4
    if not out["walk_forward"]["passed"]:
        assert "holdout" not in out and out["promote"] is False
    naive = v.naive(b, cands, proto)
    assert naive["arm"] == "naive" and naive["trials"] == 16

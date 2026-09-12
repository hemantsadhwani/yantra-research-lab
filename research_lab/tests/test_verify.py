"""The verification hook must FAIL LOUDLY. These tests prove it does."""
from __future__ import annotations

import math

from research_lab.schemas import BacktestResult, StrategyVariant
from research_lab.verify import VerificationError, verify_result, verify_variant
from synthetic_engine import DEFAULT_STRATEGY, get_baseline

GOOD_PARAMS = get_baseline(DEFAULT_STRATEGY)


def _variant(pid="v001", **over):
    p = dict(GOOD_PARAMS)
    p.update(over)
    return StrategyVariant(id=pid, params=p, rationale="test")


def _result(vid="v001", **over):
    base = {"variant_id": vid, "total_return_pct": 12.0, "trades": 20,
            "win_rate": 0.6, "max_drawdown_pct": 5.0, "sharpe": 1.2}
    base.update(over)
    return BacktestResult(**base)


def _raises(fn, *a):
    try:
        fn(*a)
    except VerificationError:
        return True
    return False


CHECKS = [
    ("valid result passes",          lambda: not _raises(verify_result, _result(), _variant())),
    ("valid variant passes",         lambda: not _raises(verify_variant, _variant())),
    ("NaN return raises",            lambda: _raises(verify_result, _result(total_return_pct=float("nan")), _variant())),
    ("inf sharpe raises",            lambda: _raises(verify_result, _result(sharpe=math.inf), _variant())),
    ("win_rate above 1 raises",      lambda: _raises(verify_result, _result(win_rate=1.4), _variant())),
    ("negative drawdown raises",     lambda: _raises(verify_result, _result(max_drawdown_pct=-3.0), _variant())),
    ("negative trades raises",       lambda: _raises(verify_result, _result(trades=-1), _variant())),
    ("id mismatch raises",           lambda: _raises(verify_result, _result(vid="v999"), _variant("v001"))),
    ("0 trades with a return raises", lambda: _raises(verify_result, _result(trades=0, win_rate=0.0), _variant())),
    ("param out of range raises",    lambda: _raises(verify_variant, _variant(lookback=999.0))),
    ("missing param raises",         lambda: _raises(verify_variant, StrategyVariant("v1", {"lookback": 20.0}, "x"))),
]


def main() -> int:
    ok = 0
    for name, fn in CHECKS:
        r = fn()
        ok += bool(r)
        print(f"  [{'PASS' if r else 'FAIL'}] {name}")
    print(f"\n  {ok}/{len(CHECKS)} verification checks behave correctly")
    return 0 if ok == len(CHECKS) else 1


if __name__ == "__main__":
    raise SystemExit(main())

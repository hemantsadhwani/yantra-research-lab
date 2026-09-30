"""The verification hook must FAIL LOUDLY. These tests prove it does.

Two ways to run it:

    pytest -q research_lab/tests/test_verify.py      # CI: one test per scenario
    python -m research_lab.tests.test_verify         # script: PASS/FAIL table

Every "fails loudly" scenario is a ``pytest.raises(VerificationError)`` test, so a hook
that silently accepts a bad result fails the build instead of scoring a NaN.
"""
from __future__ import annotations

import math
from collections.abc import Callable

import pytest

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


# (name, zero-arg call) — each MUST pass without raising.
PASSES: list[tuple[str, Callable[[], None]]] = [
    ("valid result passes",  lambda: verify_result(_result(), _variant())),
    ("valid variant passes", lambda: verify_variant(_variant())),
]

# (name, zero-arg call, message fragment) — each MUST raise VerificationError.
RAISES: list[tuple[str, Callable[[], None], str]] = [
    ("NaN return raises",
     lambda: verify_result(_result(total_return_pct=float("nan")), _variant()), "finite"),
    ("inf sharpe raises",
     lambda: verify_result(_result(sharpe=math.inf), _variant()), "finite"),
    ("win_rate above 1 raises",
     lambda: verify_result(_result(win_rate=1.4), _variant()), "win_rate"),
    ("negative drawdown raises",
     lambda: verify_result(_result(max_drawdown_pct=-3.0), _variant()), "drawdown"),
    ("negative trades raises",
     lambda: verify_result(_result(trades=-1), _variant()), "trades"),
    ("id mismatch raises",
     lambda: verify_result(_result(vid="v999"), _variant("v001")), "v999"),
    ("0 trades with a return raises",
     lambda: verify_result(_result(trades=0, win_rate=0.0), _variant()), "trades"),
    ("param out of range raises",
     lambda: verify_variant(_variant(lookback=999.0)), "lookback"),
    ("missing param raises",
     lambda: verify_variant(StrategyVariant("v1", {"lookback": 20.0}, "x")), "missing"),
]


def _raises(fn: Callable[[], None]) -> bool:
    try:
        fn()
    except VerificationError:
        return True
    return False


# The script's view: (name, check) where check() is True when the hook behaves correctly.
CHECKS: list[tuple[str, Callable[[], bool]]] = [
    *[(name, (lambda f=fn: not _raises(f))) for name, fn in PASSES],
    *[(name, (lambda f=fn: _raises(f))) for name, fn, _ in RAISES],
]


@pytest.mark.parametrize("name,fn", CHECKS, ids=[n for n, _ in CHECKS])
def test_check_behaves(name, fn):
    assert fn(), f"verification check misbehaved: {name}"


@pytest.mark.parametrize("name,fn", PASSES, ids=[n for n, _ in PASSES])
def test_valid_input_passes(name, fn):
    fn()  # must not raise


@pytest.mark.parametrize("name,fn,match", RAISES, ids=[n for n, _, _ in RAISES])
def test_hook_fails_loudly(name, fn, match):
    with pytest.raises(VerificationError, match=match):
        fn()


def test_verification_error_is_an_assertion_error():
    # Loud by construction: an un-caught VerificationError fails any test or CI step.
    assert issubclass(VerificationError, AssertionError)


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

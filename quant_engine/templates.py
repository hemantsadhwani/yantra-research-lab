"""Strategy templates: the only strategies agents may run on the public engine.

A template turns bars + parameters into a position per bar (1 = long, 0 = flat), decided at
bar t's CLOSE with data up to t; the backtester fills it at bar t+1's OPEN. Agents choose
templates and parameters; they never write strategy code (generated code would need a
sandbox and a look-ahead audit; see docs). Every template shares three optional filters:

    trend_ema  only hold long while close > EMA(trend_ema)      (0 = off)
    vix_max    only ENTER when the VIX close <= vix_max          (0 = off)
    atr_stop   exit when close < entry close - atr_stop * ATR(14) (0 = off)
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from quant_engine import indicators as ind
from quant_engine.data import Bars

FILTER_SPACE: dict[str, list[float]] = {
    "trend_ema": [0, 100, 200],
    "vix_max": [0, 20, 25, 30],
    "atr_stop": [0, 2.0, 3.0],
}


@dataclass(frozen=True)
class Template:
    name: str
    style: str                          # continuation | reversal | pullback
    description: str
    space: dict[str, list[float]]       # the template's own parameters (grid values)
    rule: Callable[[Bars, dict], tuple[list[bool], list[bool]]] = field(repr=False)
    # rule -> (enter[t], exit[t]) booleans from data up to t; filters are applied on top

    def full_space(self, with_filters: bool = True) -> dict[str, list[float]]:
        return {**self.space, **(FILTER_SPACE if with_filters else {})}


def _cmp(a: Sequence[float | None], b: Sequence[float | None], op) -> list[bool]:
    return [x is not None and y is not None and op(x, y) for x, y in zip(a, b, strict=True)]


# ---------- the five rules ----------
def ema_cross(b: Bars, p: dict) -> tuple[list[bool], list[bool]]:
    fast, slow = ind.ema(b.close, int(p["fast"])), ind.ema(b.close, int(p["slow"]))
    up = _cmp(fast, slow, lambda x, y: x > y)
    return up, [not u for u in up]


def donchian_breakout(b: Bars, p: dict) -> tuple[list[bool], list[bool]]:
    hi, lo = ind.prior_max(b.high, int(p["entry_n"])), ind.prior_min(b.low, int(p["exit_n"]))
    return _cmp(b.close, hi, lambda c, h: c > h), _cmp(b.close, lo, lambda c, low: c < low)


def rsi_reversion(b: Bars, p: dict) -> tuple[list[bool], list[bool]]:
    r = ind.rsi(b.close, int(p["n"]))
    return ([x is not None and x < p["entry"] for x in r],
            [x is not None and x > p["exit"] for x in r])


def bollinger_reversion(b: Bars, p: dict) -> tuple[list[bool], list[bool]]:
    n, k = int(p["n"]), p["k"]
    mid, sd = ind.sma(b.close, n), ind.rolling_std(b.close, n)
    lower = [None if m is None or s is None else m - k * s for m, s in zip(mid, sd, strict=True)]
    return _cmp(b.close, lower, lambda c, x: c < x), _cmp(b.close, mid, lambda c, m: c > m)


def fib_pullback(b: Bars, p: dict) -> tuple[list[bool], list[bool]]:
    """Buy a retracement of the prior swing in an uptrend: close falls to within the
    `level` retracement of the last `swing_n` bars' range; exit at the swing high or on
    a break of the swing low."""
    n, level = int(p["swing_n"]), p["level"]
    hi, lo = ind.prior_max(b.high, n), ind.prior_min(b.low, n)
    trend = ind.ema(b.close, 100)
    enter, exit_ = [], []
    for t, c in enumerate(b.close):
        h, low, e = hi[t], lo[t], trend[t]
        ok = h is not None and low is not None and e is not None and h > low
        enter.append(ok and c > e and low < c <= h - level * (h - low))
        exit_.append(ok and (c >= h or c < low))
    return enter, exit_


TEMPLATES: dict[str, Template] = {t.name: t for t in (
    Template("ema_cross", "continuation", "Long while the fast EMA is above the slow EMA.",
             {"fast": [5, 10, 20, 30], "slow": [50, 100, 150, 200]}, ema_cross),
    Template("donchian_breakout", "continuation",
             "Enter on a close above the prior N-day high; exit below the prior M-day low.",
             {"entry_n": [20, 55, 100], "exit_n": [10, 20, 50]}, donchian_breakout),
    Template("rsi_reversion", "reversal", "Buy when RSI is oversold; sell when it recovers.",
             {"n": [2, 3, 5, 14], "entry": [10, 20, 30], "exit": [50, 60, 70]}, rsi_reversion),
    Template("bollinger_reversion", "reversal",
             "Buy a close below the lower Bollinger band; exit at the middle band.",
             {"n": [10, 20, 40], "k": [1.5, 2.0, 2.5]}, bollinger_reversion),
    Template("fib_pullback", "pullback",
             "In an uptrend, buy a Fibonacci retracement of the prior swing.",
             {"swing_n": [20, 40, 60], "level": [0.382, 0.5, 0.618]}, fib_pullback),
)}


def positions(b: Bars, template: str, params: dict) -> list[int]:
    """Position decided at each bar's close (filled next open). Causal by construction."""
    t = TEMPLATES[template]
    enter, exit_ = t.rule(b, params)
    trend_n, vix_max, k = int(params.get("trend_ema", 0)), params.get("vix_max", 0), params.get("atr_stop", 0)
    trend = ind.ema(b.close, trend_n) if trend_n else None
    atr = ind.atr(b.high, b.low, b.close, 14) if k else None
    pos, out, entry_close = 0, [], 0.0
    for i, c in enumerate(b.close):
        trend_ok = trend is None or (trend[i] is not None and c > trend[i])
        if pos:
            stop = atr is not None and atr[i] is not None and c < entry_close - k * atr[i]
            if exit_[i] or stop or not trend_ok:
                pos = 0
        elif enter[i] and trend_ok and (not vix_max or (b.vix is not None and b.vix[i] <= vix_max)):
            pos, entry_close = 1, c
        out.append(pos)
    return out

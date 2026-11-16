"""Causal indicators over plain lists. Every value at index t uses data up to and including t,
never later; ``None`` marks the warm-up. ``tests/test_lookahead.py`` checks this property for
every strategy template by recomputing on truncated data."""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Sequence

Series = list[float | None]


def sma(x: Sequence[float], n: int) -> Series:
    out: Series = [None] * len(x)
    s = 0.0
    for i, v in enumerate(x):
        s += v
        if i >= n:
            s -= x[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def ema(x: Sequence[float], n: int) -> Series:
    """Exponential moving average, seeded with the SMA of the first n values."""
    out: Series = [None] * len(x)
    if len(x) < n:
        return out
    a = 2.0 / (n + 1)
    e = sum(x[:n]) / n
    out[n - 1] = e
    for i in range(n, len(x)):
        e = a * x[i] + (1 - a) * e
        out[i] = e
    return out


def rolling_std(x: Sequence[float], n: int) -> Series:
    out: Series = [None] * len(x)
    s = s2 = 0.0
    for i, v in enumerate(x):
        s += v
        s2 += v * v
        if i >= n:
            s -= x[i - n]
            s2 -= x[i - n] ** 2
        if i >= n - 1:
            m = s / n
            out[i] = math.sqrt(max(0.0, s2 / n - m * m))
    return out


def rsi(close: Sequence[float], n: int) -> Series:
    """Wilder's RSI."""
    out: Series = [None] * len(close)
    if len(close) <= n:
        return out
    gains = losses = 0.0
    for i in range(1, n + 1):
        d = close[i] - close[i - 1]
        gains += max(d, 0.0)
        losses += max(-d, 0.0)
    ag, al = gains / n, losses / n
    out[n] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    for i in range(n + 1, len(close)):
        d = close[i] - close[i - 1]
        ag = (ag * (n - 1) + max(d, 0.0)) / n
        al = (al * (n - 1) + max(-d, 0.0)) / n
        out[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def atr(high: Sequence[float], low: Sequence[float], close: Sequence[float], n: int) -> Series:
    """Wilder's average true range."""
    out: Series = [None] * len(close)
    if len(close) <= n:
        return out
    tr = [high[0] - low[0]] + [
        max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
        for i in range(1, len(close))
    ]
    a = sum(tr[1:n + 1]) / n
    out[n] = a
    for i in range(n + 1, len(close)):
        a = (a * (n - 1) + tr[i]) / n
        out[i] = a
    return out


def prior_max(x: Sequence[float], n: int) -> Series:
    """Highest value of the n bars BEFORE t (excludes t): a breakout compares close[t] to it."""
    return _prior_extreme(x, n, max)


def prior_min(x: Sequence[float], n: int) -> Series:
    return _prior_extreme(x, n, min)


def _prior_extreme(x: Sequence[float], n: int, pick) -> Series:
    out: Series = [None] * len(x)
    q: deque[int] = deque()
    better = (lambda a, b: a >= b) if pick is max else (lambda a, b: a <= b)
    for i in range(len(x)):
        if i >= n:
            out[i] = x[q[0]]
        # add x[i] for the window used at i+1
        while q and better(x[i], x[q[-1]]):
            q.pop()
        q.append(i)
        if q[0] <= i - n:
            q.popleft()
    return out

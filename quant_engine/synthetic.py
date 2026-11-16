"""Synthetic daily markets with a known answer, for the planted-edge benchmark.

``noise``   : no edge. Volatility clusters (two persistent regimes), which is exactly what
              makes grid search "find" patterns that are not there.
``trend``   : persistent up/down drift regimes; trend-following templates can capture it.
``meanrev`` : short-horizon reversion (an AR(1) deviation around a random walk); oversold
              templates can capture it.

Same volatility process in all three, so the only difference is the planted structure.
Deterministic per seed. A VIX-like series is derived from the true volatility regime.
"""

from __future__ import annotations

import datetime as dt
import math
import random

from quant_engine.data import Bars

KINDS = ("noise", "trend", "meanrev")

# Edge strengths, calibrated on seeds 1000-1099 only (the benchmark uses seeds 1-20).
TREND_SWITCH = 0.008
TREND_DRIFT = 0.0019
MEANREV_SCALE = 0.6


def business_days(start: dt.date, n: int) -> list[str]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += dt.timedelta(days=1)
    return out


def generate(kind: str, seed: int, n: int = 4000, strength: float = 1.0) -> Bars:
    if kind not in KINDS:
        raise ValueError(kind)
    rng = random.Random(seed)
    vol_state, trend_state = 0, 1
    dev = 0.0           # mean-reversion deviation (log)
    base = math.log(10000.0)
    closes, opens, highs, lows, vix = [], [], [], [], []
    prev_close = 10000.0
    for _ in range(n):
        if rng.random() < 0.01:                       # vol regime switch, ~100-day regimes
            vol_state ^= 1
        sigma = 0.008 if vol_state == 0 else 0.017
        drift = 0.0   # no reward for just being long: an edge must come from structure
        if kind == "trend":
            if rng.random() < TREND_SWITCH:           # ~125-day trend regimes
                trend_state = -trend_state
            drift += trend_state * TREND_DRIFT * strength
        shock = rng.gauss(0, sigma)
        if kind == "meanrev":
            # observed log price = random-walk base + AR(1) deviation that decays quickly
            base += drift + shock * 0.6
            dev = 0.55 * dev + rng.gauss(0, sigma * MEANREV_SCALE * strength)
            log_close = base + dev
        else:
            base += drift + shock
            log_close = base
        close = math.exp(log_close)
        gap = rng.gauss(0, sigma * 0.25)
        open_ = prev_close * math.exp(gap)
        hi = max(open_, close) * math.exp(abs(rng.gauss(0, sigma * 0.5)))
        lo = min(open_, close) * math.exp(-abs(rng.gauss(0, sigma * 0.5)))
        opens.append(open_)
        closes.append(close)
        highs.append(hi)
        lows.append(lo)
        vix.append(round(100 * sigma * math.sqrt(252) * (1 + rng.gauss(0, 0.08)), 2))
        prev_close = close
    return Bars(business_days(dt.date(2010, 1, 4), n), opens, highs, lows, closes, vix)

"""Daily long/flat backtest with next-open fills and per-trade costs.

A position decided at bar t's close is filled at bar t+1's open. Day t+1's return is the
overnight gap earned by the position held into the open plus the open-to-close move earned by
the new position, minus cost on any change:

    r[t+1] = pos[t-1] * (open[t+1] / close[t] - 1) + pos[t] * (close[t+1] / open[t+1] - 1)
             - cost * |pos[t] - pos[t-1]|
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from quant_engine.data import Bars

YEAR = 252


@dataclass
class Result:
    returns: list[float]          # daily strategy returns, aligned to bars (r[0] = 0)
    trades: list[tuple[int, int, float]]   # (entry bar, exit bar, net return)


def run(b: Bars, pos: Sequence[int], cost_bps: float = 5.0) -> Result:
    cost = cost_bps / 1e4
    n = len(b)
    r = [0.0] * n
    trades: list[tuple[int, int, float]] = []
    entry_bar, entry_px = -1, 0.0
    for t in range(n - 1):
        prev = pos[t - 1] if t else 0
        cur = pos[t]
        o, c0, c1 = b.open[t + 1], b.close[t], b.close[t + 1]
        r[t + 1] = prev * (o / c0 - 1) + cur * (c1 / o - 1) - cost * abs(cur - prev)
        if cur and not prev:
            entry_bar, entry_px = t + 1, o
        elif prev and not cur and entry_bar >= 0:
            trades.append((entry_bar, t + 1, o / entry_px - 1 - 2 * cost))
            entry_bar = -1
    return Result(r, trades)


def sharpe(r: Sequence[float]) -> float:
    n = len(r)
    if n < 2:
        return 0.0
    m = sum(r) / n
    var = sum((x - m) ** 2 for x in r) / (n - 1)
    return 0.0 if var <= 0 else m / math.sqrt(var) * math.sqrt(YEAR)


def metrics(res: Result, a: int, b: int) -> dict:
    """Metrics over bars [a, b)."""
    r = res.returns[a:b]
    eq, peak, mdd = 1.0, 1.0, 0.0
    for x in r:
        eq *= 1 + x
        peak = max(peak, eq)
        mdd = max(mdd, 1 - eq / peak)
    years = max(len(r) / YEAR, 1e-9)
    tr = [t for t in res.trades if a <= t[0] < b]
    return {
        "days": len(r),
        "total_return_pct": round(100 * (eq - 1), 2),
        "cagr_pct": round(100 * (eq ** (1 / years) - 1), 2) if eq > 0 else -100.0,
        "sharpe": round(sharpe(r), 3),
        "max_drawdown_pct": round(100 * mdd, 2),
        "exposure_pct": round(100 * sum(1 for x in r if x != 0) / max(len(r), 1), 1),
        "trades": len(tr),
        "win_rate_pct": round(100 * sum(1 for t in tr if t[2] > 0) / len(tr), 1) if tr else None,
    }

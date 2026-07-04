"""A deterministic toy mean-reversion backtest over a synthetic price series.

Pure standard library so a fresh clone runs with no dependencies. The market series
is fixed by ``MARKET_SEED`` — every strategy variant is evaluated on the *same* data,
which is the backtest-parity discipline made concrete (no variant gets luckier data).

This is intentionally simple and public. It is NOT the production strategy; it only
provides a realistic propose -> backtest -> rank surface for the agent loop.
"""

from __future__ import annotations

import math
import random
from typing import Any

MARKET_SEED = 20260704
SERIES_LEN = 2000

# The tunable knobs a proposer may vary, with valid ranges (clamped on proposal).
PARAM_SPACE: dict[str, tuple[float, float]] = {
    "lookback": (10, 80),      # rolling window for the z-score
    "z_entry": (0.5, 3.0),     # enter long when z <= -z_entry (oversold)
    "z_exit": (-1.0, 1.5),     # exit when z >= -z_exit (reverted)
    "stop_pct": (0.5, 6.0),    # hard stop, percent from entry
}

# A deliberately mediocre, untuned baseline the agents must beat (waits for very deep
# dips on a long window with a tight stop -> few trades, ~coin-flip win rate).
BASELINE_PARAMS: dict[str, float] = {
    "lookback": 50,
    "z_entry": 2.5,
    "z_exit": -0.5,
    "stop_pct": 1.5,
}


def _synthetic_prices(seed: int = MARKET_SEED, n: int = SERIES_LEN) -> list[float]:
    """An Ornstein-Uhlenbeck-like mean-reverting series — gives a real edge to
    buying oversold dips, so parameter choice actually matters."""
    rng = random.Random(seed)
    mu = 100.0
    price = mu
    prices = [price]
    for _ in range(n - 1):
        drift = 0.02 * (mu - price)          # pull back toward the mean
        shock = rng.gauss(0.0, 0.6)          # noise
        price = max(1.0, price + drift + shock)
        prices.append(price)
    return prices


def run_backtest(params: dict[str, Any], market_seed: int = MARKET_SEED) -> dict[str, Any]:
    """Run the long-only mean-reversion strategy and return risk/return metrics.

    Deterministic given ``(params, market_seed)`` — same inputs, same output.
    """
    lookback = max(2, int(round(params["lookback"])))
    z_entry = float(params["z_entry"])
    z_exit = float(params["z_exit"])
    stop_pct = float(params["stop_pct"])

    prices = _synthetic_prices(market_seed)
    n = len(prices)

    in_pos = False
    entry_price = 0.0
    trade_returns: list[float] = []  # per-trade % returns

    for i in range(lookback, n):
        window = prices[i - lookback : i]
        mean = sum(window) / lookback
        var = sum((p - mean) ** 2 for p in window) / lookback
        std = math.sqrt(var) or 1e-9
        z = (prices[i] - mean) / std

        if not in_pos:
            if z <= -z_entry:                       # oversold -> go long
                in_pos = True
                entry_price = prices[i]
        else:
            ret = (prices[i] - entry_price) / entry_price * 100.0
            hit_stop = ret <= -stop_pct
            reverted = z >= -z_exit                  # mean-reverted back up
            if hit_stop or reverted or i == n - 1:
                trade_returns.append(ret)
                in_pos = False

    trades = len(trade_returns)
    if trades == 0:
        return {
            "total_return_pct": 0.0, "trades": 0, "win_rate": 0.0,
            "max_drawdown_pct": 0.0, "sharpe": 0.0,
        }

    wins = sum(1 for r in trade_returns if r > 0)
    total_return = sum(trade_returns)

    # equity curve -> max drawdown
    equity, peak, max_dd = 0.0, 0.0, 0.0
    for r in trade_returns:
        equity += r
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)

    mean_r = total_return / trades
    sd_r = math.sqrt(sum((r - mean_r) ** 2 for r in trade_returns) / trades) or 1e-9
    sharpe = mean_r / sd_r * math.sqrt(trades)   # per-run pseudo-Sharpe

    return {
        "total_return_pct": round(total_return, 2),
        "trades": trades,
        "win_rate": round(wins / trades, 4),
        "max_drawdown_pct": round(max_dd, 2),
        "sharpe": round(sharpe, 3),
    }

"""A deterministic toy mean-reversion backtest over a synthetic price series.

Pure standard library so a fresh clone runs with no dependencies. The market series
is fixed by each strategy's seed — every strategy variant is evaluated on the *same*
data, which is the backtest-parity discipline made concrete (no variant gets luckier
data).

This is intentionally simple and public. It is NOT the production strategy; it only
provides a realistic propose -> backtest -> rank surface for the agent loop.

**Named strategies (IP boundary).** ``nifty-weekday``, ``nifty-expiry`` and
``sensex-expiry`` are the real production strategies *by name only*. Here they are
synthetic stand-ins that differ solely in their public market *profile* (seed, reversion
strength, noise) — the real entry/exit logic is proprietary and runs server-side behind
this same ``run_backtest(...)`` contract. The public agent loop can drive either engine
because both speak the same contract; only the innermost edge is swapped for a stand-in.
See ADR-0001 / ADR-0002.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Any

SERIES_LEN = 2000

# The tunable knobs a proposer may vary, with valid ranges (clamped on proposal).
# Shared across strategies — the *contract* is stable; only the market profile differs.
PARAM_SPACE: dict[str, tuple[float, float]] = {
    "lookback": (10, 80),      # rolling window for the z-score
    "z_entry": (0.5, 3.0),     # enter long when z <= -z_entry (oversold)
    "z_exit": (-1.0, 1.5),     # exit when z >= -z_exit (reverted)
    "stop_pct": (0.5, 6.0),    # hard stop, percent from entry
}


@dataclass(frozen=True)
class StrategyProfile:
    """Public shape of a synthetic market. Carries ZERO proprietary logic — it only
    seeds a mean-reverting price series and picks the (deliberately mediocre) baseline
    the agents must beat. The real strategy of the same ``name`` is private."""
    name: str
    market_seed: int
    reversion: float                 # OU pull-back strength toward the mean
    noise: float                     # per-step shock stdev
    baseline: dict[str, float]       # untuned baseline every variant is judged against


# A deliberately mediocre, untuned baseline (waits for very deep dips on a long window
# with a tight stop -> few trades, ~coin-flip win rate) reused across profiles.
_MEDIOCRE_BASELINE: dict[str, float] = {
    "lookback": 50,
    "z_entry": 2.5,
    "z_exit": -0.5,
    "stop_pct": 1.5,
}

# The default profile reproduces the original single-strategy engine byte-for-byte
# (seed 20260704, reversion 0.02, noise 0.6) so existing runs/eval-gate are unchanged.
# The three named profiles are synthetic stand-ins for the private production strategies;
# their differing (seed, reversion, noise) give the agent loop three distinct surfaces to
# research — mirroring that the real products behave differently — without revealing any IP.
STRATEGIES: dict[str, StrategyProfile] = {
    "synthetic-meanrev": StrategyProfile("synthetic-meanrev", 20260704, 0.020, 0.60, _MEDIOCRE_BASELINE),
    "nifty-weekday":     StrategyProfile("nifty-weekday",     20260711, 0.030, 0.70, _MEDIOCRE_BASELINE),
    "nifty-expiry":      StrategyProfile("nifty-expiry",      20260718, 0.015, 0.90, _MEDIOCRE_BASELINE),
    "sensex-expiry":     StrategyProfile("sensex-expiry",     20260725, 0.025, 1.10, _MEDIOCRE_BASELINE),
}

DEFAULT_STRATEGY = "synthetic-meanrev"

# Back-compat module constants (the default profile).
MARKET_SEED = STRATEGIES[DEFAULT_STRATEGY].market_seed
BASELINE_PARAMS: dict[str, float] = dict(STRATEGIES[DEFAULT_STRATEGY].baseline)


def list_strategies() -> list[str]:
    """Names the agent loop can target — synthetic stand-ins for the real products."""
    return list(STRATEGIES)


def get_baseline(strategy: str = DEFAULT_STRATEGY) -> dict[str, float]:
    """The baseline params a strategy's variants are judged against."""
    return dict(_resolve(strategy).baseline)


def _resolve(strategy: str) -> StrategyProfile:
    try:
        return STRATEGIES[strategy]
    except KeyError:
        raise ValueError(f"unknown strategy {strategy!r}; choose from {list_strategies()}") from None


def _synthetic_prices(profile: StrategyProfile, n: int = SERIES_LEN) -> list[float]:
    """An Ornstein-Uhlenbeck-like mean-reverting series — gives a real edge to
    buying oversold dips, so parameter choice actually matters."""
    rng = random.Random(profile.market_seed)
    mu = 100.0
    price = mu
    prices = [price]
    for _ in range(n - 1):
        drift = profile.reversion * (mu - price)   # pull back toward the mean
        shock = rng.gauss(0.0, profile.noise)      # noise
        price = max(1.0, price + drift + shock)
        prices.append(price)
    return prices


def run_backtest(params: dict[str, Any], strategy: str = DEFAULT_STRATEGY) -> dict[str, Any]:
    """Run the long-only mean-reversion strategy and return risk/return metrics.

    Deterministic given ``(params, strategy)`` — same inputs, same output. ``strategy``
    selects the (synthetic) market profile; the real strategy of that name is private and
    served behind this identical contract.
    """
    profile = _resolve(strategy)
    lookback = max(2, int(round(params["lookback"])))
    z_entry = float(params["z_entry"])
    z_exit = float(params["z_exit"])
    stop_pct = float(params["stop_pct"])

    prices = _synthetic_prices(profile)
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

<!-- product: nifty-expiry | book: nifty-expiry-low-vix | status: LIVE | as_of: 2026-09-12 -->
# NIFTY expiry — LOW-VIX book (backtest outputs)

The expiry-day (0DTE) NIFTY book on quiet Tuesdays; same book as the high-VIX profile, harvested differently. Runs LIVE in production. This covers the backtest period 2025-09 to 2026-09. These are backtest outputs with simulated fills and a per-trade slippage charge; P&L is in points, summed not compounded; not a performance promise.

Headline:
- Book P&L +339.11 points over 65 trades in 28 sessions
- Win rate 63.1% (41 wins / 24 losses)
- Per trade +5.22 points, per session +12.11 points
- Months up 7 of 8 traded
- Top 5 trades are 76% of the book

What it costs:
- Worst day -31.74 points (about -₹32,167)
- Max drawdown -31.74 points (about -₹32,167)
- Best day +75.81 points (about ₹74,781)
- Days up 13 of 18 traded days
- Daily gate: M2M halt at -25% of the book's own base capital

Sizing: ₹1,00,000 per leg, lot size 65, 22–48 lots per leg, average deployed ₹98,457, peak reserve ₹1,96,254, net P&L ₹3,32,551, slippage 1.0% per trade.

Month by month:
- 2025-09: +52.85 points
- 2025-10: -31.74 points
- 2025-11: +1.95 points
- 2025-12: +123.82 points
- 2026-01: +92.43 points
- 2026-02: 0.00 points
- 2026-06: 0.00 points
- 2026-07: +14.90 points
- 2026-08: +74.96 points
- 2026-09: +9.94 points
- Cumulative: +339.11 points

Caveat: Smallest book in the set at 65 trades — treat a single month here as anecdote, not signal.

Not published, by design: the engine, indicators, thresholds, entry/exit rules and trade-level data. Ask about the methodology instead.

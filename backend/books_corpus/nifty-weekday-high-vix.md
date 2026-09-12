<!-- product: nifty-weekday | book: nifty-weekday-high-vix | status: LIVE | as_of: 2026-09-12 -->
# NIFTY weekday — HIGH-VIX book (backtest outputs)

The high-volatility half of the NIFTY weekday book — runs only on days India VIX opens in the high-vol band. Runs LIVE in production. This covers the backtest period 2025-10 to 2026-09. These are backtest outputs with simulated fills and a per-trade slippage charge; P&L is in points, summed not compounded; not a performance promise.

Headline:
- Book P&L +901.08 points over 204 trades in 71 sessions
- Win rate 50.0% (102 wins / 102 losses)
- Per trade +4.42 points, per session +12.69 points
- Months up 7 of 9 traded
- Top 5 trades are 52% of the book

What it costs:
- Worst day -33.79 points (about -₹82,572)
- Max drawdown -62.23 points (about -₹1,53,556)
- Best day +176.68 points (about ₹4,35,120)
- Days up 32 of 46 traded days
- Daily gate: M2M halt at -27% of the book's own base capital

Sizing: ₹2,50,000 per leg, lot size 65, 13–63 lots per leg, average deployed ₹2,45,336, peak reserve ₹4,95,202, net P&L ₹22,14,089, slippage 0.6% per trade.

Month by month:
- 2025-10: +143.73 points
- 2025-11: +89.81 points
- 2026-01: +364.87 points
- 2026-02: +170.97 points
- 2026-03: +133.78 points
- 2026-04: -10.73 points
- 2026-07: +13.24 points
- 2026-08: +49.53 points
- 2026-09: -54.12 points
- Cumulative: +901.08 points

Caveat: Top 5 trades are 52% of this book — a month without one reads flat, and that is normal.

Not published, by design: the engine, indicators, thresholds, entry/exit rules and trade-level data. Ask about the methodology instead.

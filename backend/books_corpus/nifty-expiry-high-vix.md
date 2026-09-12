<!-- product: nifty-expiry | book: nifty-expiry-high-vix | status: LIVE | as_of: 2026-09-12 -->
# NIFTY expiry — HIGH-VIX book (backtest outputs)

The expiry-day (0DTE) NIFTY book on high-volatility Tuesdays, with its own hours, zones and sizing versus the weekday book. Runs LIVE in production. This covers the backtest period 2026-01 to 2026-07. These are backtest outputs with simulated fills and a per-trade slippage charge; P&L is in points, summed not compounded; not a performance promise.

Headline:
- Book P&L +796.62 points over 85 trades in 23 sessions
- Win rate 50.6% (43 wins / 42 losses)
- Per trade +9.37 points, per session +34.64 points
- Months up 6 of 7 traded
- Top 5 trades are 53% of the book

What it costs:
- Worst day -38.00 points (about -₹94,070)
- Max drawdown -107.49 points (about -₹2,66,979)
- Best day +213.42 points (about ₹5,30,366)
- Days up 14 of 21 traded days
- Daily gate: M2M halt at -33% of the book's own base capital

Sizing: ₹2,50,000 per leg, lot size 65, 32–124 lots per leg, average deployed ₹2,48,105, peak reserve ₹4,96,935, net P&L ₹19,79,590, slippage 1.0% per trade.

Month by month:
- 2026-01: +195.02 points
- 2026-02: +78.61 points
- 2026-03: +114.42 points
- 2026-04: +100.16 points
- 2026-05: +282.09 points
- 2026-06: +34.73 points
- 2026-07: -8.41 points
- Cumulative: +796.62 points

Caveat: 0DTE: premium decays all day, so a stalled winner is a loser that has not printed yet.

Not published, by design: the engine, indicators, thresholds, entry/exit rules and trade-level data. Ask about the methodology instead.

<!-- product: sensex-expiry | book: sensex-expiry | status: LIVE | as_of: 2026-09-12 -->
# SENSEX expiry — Expiry book (backtest outputs)

The SENSEX expiry-day (0DTE) book and the largest earner in the set, traded end-to-end through the broker. Runs LIVE in production. This covers the backtest period 2025-09 to 2026-09. These are backtest outputs with simulated fills and a per-trade slippage charge; P&L is in points, summed not compounded; not a performance promise.

Headline:
- Book P&L +5930.64 points over 470 trades in 47 sessions
- Win rate 50.9% (239 wins / 231 losses)
- Per trade +12.62 points, per session +126.18 points
- Months up 13 of 13 traded
- Top 5 trades are 34% of the book

What it costs:
- Worst day -69.27 points (about -₹69,004)
- Max drawdown -172.04 points (about -₹1,70,254)
- Best day +1254.43 points (about ₹12,39,390)
- Days up 27 of 47 traded days
- Daily gate: M2M halt at -50% of the book's own base capital

Sizing: ₹1,00,000 per leg, lot size 20, 19–163 lots per leg, average deployed ₹98,716, peak reserve ₹1,99,864, net P&L ₹58,55,118, slippage 1.0% per trade.

Month by month:
- 2025-09: +319.13 points
- 2025-10: +1094.82 points
- 2025-11: +354.78 points
- 2025-12: +1053.96 points
- 2026-01: +145.61 points
- 2026-02: +1223.15 points
- 2026-03: +86.11 points
- 2026-04: +157.92 points
- 2026-05: +249.53 points
- 2026-06: +463.16 points
- 2026-07: +572.05 points
- 2026-08: +77.76 points
- 2026-09: +132.66 points
- Cumulative: +5930.64 points

Caveat: The -50% day gate is by far the loosest in the set; one bad SENSEX expiry can cost half the book's start capital.

Not published, by design: the engine, indicators, thresholds, entry/exit rules and trade-level data. Ask about the methodology instead.

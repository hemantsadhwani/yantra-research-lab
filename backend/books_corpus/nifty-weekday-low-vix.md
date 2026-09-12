<!-- product: nifty-weekday | book: nifty-weekday-low-vix | status: LIVE | as_of: 2026-09-12 -->
# NIFTY weekday — LOW-VIX book (backtest outputs)

The low-volatility half of the NIFTY weekday book — runs only on days India VIX opens in the low-vol band, on a different engine from the high-VIX half. Runs LIVE in production. This covers the backtest period 2025-09 to 2026-09. These are backtest outputs with simulated fills and a per-trade slippage charge; P&L is in points, summed not compounded; not a performance promise.

Headline:
- Book P&L +1327.39 points over 332 trades in 130 sessions
- Win rate 47.9% (159 wins / 173 losses)
- Per trade +4.00 points, per session +10.21 points
- Months up 10 of 10 traded
- Top 5 trades are 34% of the book

What it costs:
- Worst day -30.60 points (about -₹75,825)
- Max drawdown -95.84 points (about -₹2,37,338)
- Best day +163.39 points (about ₹4,05,099)
- Days up 53 of 93 traded days
- Daily gate: M2M halt at -27% of the book's own base capital

Sizing: ₹2,50,000 per leg, lot size 65, 25–63 lots per leg, average deployed ₹2,46,567, peak reserve ₹2,50,000, net P&L ₹32,72,713, slippage 0.6% per trade.

Month by month:
Monthly and daily P&L series have not been published yet — only the totals above are available. If asked for month-on-month numbers, say they are pending.

Caveat: The trailing exit carries this book: it books more than twice what the fixed stops give back.

Not published, by design: the engine, indicators, thresholds, entry/exit rules and trade-level data. Ask about the methodology instead.

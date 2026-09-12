<!-- product: nifty-weekday | book: nifty-weekday-r1s1 | status: PAPER | as_of: 2026-09-12 -->
# NIFTY weekday — R1S1 continuation book (backtest outputs)

A separate index-level continuation sub-book that runs on every weekday session in paper mode, isolated from the live book's risk gates. Runs PAPER — simulated fills, not live money. This covers the backtest period 2025-10 to 2026-09. These are backtest outputs with simulated fills and a per-trade slippage charge; P&L is in points, summed not compounded; not a performance promise.

Headline:
- Book P&L +513.75 points over 175 trades in 78 sessions
- Win rate 60.0% (105 wins / 70 losses)
- Per trade +2.94 points, per session +6.59 points
- Months up 8 of 12 traded
- Top 5 trades are 68% of the book

What it costs:
- Worst day -39.00 points (about -₹95,399)
- Max drawdown -135.75 points (about -₹3,31,767)
- Best day +239.47 points (about ₹5,79,918)
- Days up 45 of 78 traded days
- Daily gate: M2M halt at -27% of the book's own base capital

Sizing: ₹2,50,000 per leg, lot size 65, 16–35 lots per leg, average deployed ₹2,44,392, peak reserve ₹7,45,508, net P&L ₹12,54,086, slippage not separately charged.

Month by month:
Monthly and daily P&L series have not been published yet — only the totals above are available. If asked for month-on-month numbers, say they are pending.

Caveat: Runs PAPER. These are simulated fills — the LIVE flip is a capital decision, not an engineering one.

Not published, by design: the engine, indicators, thresholds, entry/exit rules and trade-level data. Ask about the methodology instead.

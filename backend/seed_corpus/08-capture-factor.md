# Capture Factor (Live-vs-Backtest Honesty Metric)

The **capture factor** is a simple honesty metric that answers: how much of the
performance a backtest promised did the strategy actually deliver in live trading?

    capture_factor = live_return / backtest_return   (over the same period)

- A capture factor near **1.0** means live results matched the backtest — the model of
  the world was faithful.
- A capture factor well **below 1.0** means the backtest was optimistic: real slippage,
  fees, latency, partial fills, or overfitting ate into the edge.
- A capture factor **above 1.0** can happen by luck or favourable conditions, but is not
  something to rely on.

## Why track it
Backtests are estimates; the capture factor grades those estimates against reality. A
persistently low capture factor is a red flag that the research process has a parity
problem (look-ahead bias, unrealistic fills) or is overfitting. Tracking capture factor
over time turns "the backtest looked great" into an accountable, measurable claim, and
keeps the research loop honest.

It is the natural companion to backtesting parity and walk-forward validation: parity
and walk-forward reduce the gap *before* going live, and the capture factor *measures*
the gap that remains.

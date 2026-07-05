# Drawdown

A **drawdown** is the decline in an equity curve from a previous peak to a subsequent
trough, expressed as a percentage of the peak:

    drawdown_t = (equity_t - running_max_equity) / running_max_equity

It is always zero or negative; it returns to zero only when a new high is made.

## Key quantities
- **Maximum drawdown (MDD):** the largest peak-to-trough decline over the sample. It
  answers "what was the worst loss an investor would have lived through?"
- **Drawdown duration:** how long it took to recover to the prior peak. Long
  underwater periods test conviction even when the eventual return is good.

## Why it matters
Drawdown captures the pain and path-dependency that averages hide. Two strategies can
share the same total return while one grinds steadily and the other suffers a
catastrophic 60% loss along the way. Position sizing, leverage limits, and stop rules
are chosen largely to keep drawdown within tolerable bounds, because a deep enough
drawdown can force liquidation or abandonment before the strategy recovers. Drawdown is
also a denominator in risk-adjusted measures such as the Calmar ratio.

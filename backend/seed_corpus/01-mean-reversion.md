# Mean Reversion

Mean reversion is the tendency of a price series (or a spread between two series) to
return toward a longer-run average after deviating from it. The trading idea is that
extreme deviations are, on average, temporary: when a series trades far above its mean
it is more likely to fall back than to keep rising, and vice versa.

## Core intuition
- Identify a reference level — a moving average, a rolling mean, or an equilibrium
  relationship (e.g. a cointegrated pair).
- Measure how far the current price sits from that reference, usually in units of
  standard deviation (a z-score) so the signal is comparable across time and assets.
- Fade the deviation: lean against large positive deviations and toward large negative
  ones, expecting convergence back to the mean.

## When it works and when it breaks
Mean reversion works best in range-bound, liquid markets where no persistent trend or
structural break is present. It performs poorly during regime changes, trending
markets, or when the "mean" itself is drifting — a stationary-looking spread can break
permanently (structural break), which is why risk controls and stop rules matter.

## Relationship to other tools
Mean reversion pairs naturally with z-scores and Bollinger Bands (which express
distance-from-mean in volatility units) and with regime detection (only trade
reversion when the market is actually in a mean-reverting regime). It is the
conceptual opposite of momentum/trend-following, which bets that deviations persist.

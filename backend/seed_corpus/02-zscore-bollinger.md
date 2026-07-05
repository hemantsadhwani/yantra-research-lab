# Z-Scores and Bollinger Bands

A **z-score** standardises a value by expressing its distance from a mean in units of
standard deviation:

    z = (x - rolling_mean) / rolling_std

A z-score of +2 means the current value is two standard deviations above its recent
average. Because it is scale-free, a z-score lets you compare "how extreme is this?"
across different instruments and time periods.

## Bollinger Bands
Bollinger Bands are a graphical expression of the same idea. They plot:
- a middle band: a simple moving average (commonly 20 periods),
- an upper band: middle + k standard deviations (commonly k = 2),
- a lower band: middle - k standard deviations.

When price touches or exceeds the upper band it is statistically stretched to the
upside; touching the lower band is stretched to the downside. The bands widen when
volatility rises and contract when it falls, so they adapt to changing conditions.

## Using them together
A common methodology is to treat a band touch (or an equivalent z-score threshold) as
a *candidate* signal, not an automatic trade. Confirmation, volatility filters, and
regime checks reduce false signals. Band width itself is informative: a prolonged
squeeze (narrow bands) often precedes a volatility expansion.

Note: the specific lookback, band multiplier, and thresholds a live strategy uses are
tuning choices — this note explains the general method, not any particular
production configuration.

# Risk-Adjusted Returns and the Sharpe Ratio

Raw return is not enough to judge a strategy: a return earned by taking enormous risk
is worth less than the same return earned smoothly. **Risk-adjusted return** measures
reward per unit of risk.

## Sharpe ratio
The Sharpe ratio is the most common risk-adjusted measure:

    Sharpe = (mean_return - risk_free_rate) / std_dev_of_returns

It divides excess return (return above a risk-free benchmark) by the volatility of
returns. A higher Sharpe means more return for each unit of volatility taken. Sharpe
is typically annualised by multiplying by the square root of the number of periods per
year (e.g. sqrt(252) for daily returns).

## Related measures
- **Sortino ratio:** like Sharpe but divides by *downside* deviation only, since
  upside volatility is not a "risk" investors dislike.
- **Calmar ratio:** annualised return divided by maximum drawdown — reward per unit of
  worst-case pain.

## Interpretation cautions
Sharpe assumes returns are roughly normal and stable; strategies with rare large
losses (fat tails) can show a flattering Sharpe right up until a blow-up. Always read
Sharpe alongside drawdown, tail risk, and the length/representativeness of the sample.

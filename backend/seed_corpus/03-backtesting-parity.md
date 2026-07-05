# Backtesting Parity

**Backtesting parity** is the principle that a backtest should reproduce, as faithfully
as possible, the exact logic, data, and constraints that a strategy would face in live
trading. A backtest that quietly uses information or assumptions unavailable in real
time will look good on paper and disappoint in production.

## Common parity breaks (biases to avoid)
- **Look-ahead bias:** using data that would not have been known at decision time
  (e.g. same-bar close to decide a same-bar entry).
- **Survivorship bias:** testing only on instruments that still exist today.
- **Fill assumptions:** assuming trades execute at prices that were never actually
  reachable; ignoring slippage, spread, and market impact.
- **Fee and cost omission:** leaving out commissions, borrow, and financing.
- **Data snooping / overfitting:** tuning parameters until the backtest looks great on
  the one history you have.

## Why parity matters
The purpose of a backtest is to estimate live behaviour. If the simulated engine and
the live engine diverge, the backtest is measuring a strategy that will never trade.
Enforcing parity — same signal code, same timestamps, realistic costs — is what makes
the estimate trustworthy. The honest end-to-end check is to compare live results
against the backtest for the same period (see: capture factor).

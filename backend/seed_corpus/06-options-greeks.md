# Options Greeks (Basics)

The **Greeks** measure how an option's price responds to changes in underlying
conditions. They are the partial derivatives of the option value with respect to each
input and are the language of options risk management.

## The primary Greeks
- **Delta (Δ):** sensitivity of option price to a $1 move in the underlying. Ranges
  ~0 to 1 for calls and ~0 to -1 for puts. Also a rough hedge ratio and an approximate
  probability of finishing in the money.
- **Gamma (Γ):** the rate of change of delta as the underlying moves. High gamma means
  delta shifts quickly, so a hedge must be rebalanced often. Gamma is largest for
  at-the-money options near expiry.
- **Theta (Θ):** time decay — how much value the option loses per day as expiration
  approaches, all else equal. Usually negative for long options.
- **Vega (ν):** sensitivity to a 1-point change in implied volatility. Long options are
  long vega; they gain when implied volatility rises.
- **Rho (ρ):** sensitivity to interest-rate changes, usually the least important for
  short-dated options.

## Why they matter
Greeks let a trader decompose and hedge risk: a book can be made delta-neutral yet
still carry gamma, vega, and theta exposure. Understanding the trade-offs — for
example, being long gamma but paying theta — is central to options methodology.

# Quant knowledge seed-list — 50 papers/texts for the ingestion backfill

The initial corpus for the knowledge base. Chosen to be **canonical** (what every quant should
know) and **multimodal-rich** (formulas, tables, diagrams) — so they also stress-test the
ingestion pipeline ([architecture/02-data-ingestion.md](../architecture/02-data-ingestion.md)).

> **Fetch by title** on arXiv / SSRN / journal / open PDFs (most classics predate arXiv).
> `📐`=formula-heavy · `📊`=tables/charts · `🖼`=diagrams — the good multimodal test cases.

## A. Foundations — pricing & stochastic calculus `📐`
1. Bachelier (1900) — *Théorie de la spéculation* `📐`
2. Black & Scholes (1973) — *The Pricing of Options and Corporate Liabilities* `📐`
3. Merton (1973) — *Theory of Rational Option Pricing* `📐`
4. Cox, Ross & Rubinstein (1979) — *Option Pricing: A Simplified Approach* (binomial tree) `📐🖼`
5. Harrison & Pliska (1981) — martingales in continuous trading `📐`

## B. Monte Carlo methods `📐📊`
6. Boyle (1977) — *Options: A Monte Carlo Approach* `📐`
7. Longstaff & Schwartz (2001) — *Valuing American Options by Simulation (LSM)* `📐📊`
8. Glasserman (2003) — *Monte Carlo Methods in Financial Engineering* (key chapters) `📐📊`
9. Broadie & Glasserman (1996) — pricing American-style securities by simulation `📐`
10. Giles (2008) — *Multilevel Monte Carlo Path Simulation* `📐📊`
11. Andersen (2008) — efficient simulation of the Heston model `📐`

## C. Volatility modelling `📐📊🖼`
12. Engle (1982) — *ARCH* `📐`
13. Bollerslev (1986) — *GARCH* `📐`
14. Heston (1993) — *Stochastic Volatility Closed-Form Solution* `📐`
15. Dupire (1994) — *Pricing with a Smile* (local vol) `📐`
16. Hagan et al. (2002) — *Managing Smile Risk (SABR)* `📐🖼`
17. Gatheral (2006) — *The Volatility Surface* (key chapters) `📐🖼`
18. Gatheral, Jaisson & Rosenbaum (2018) — *Volatility Is Rough* `📐📊`
19. Carr & Madan (1999) — option valuation via FFT `📐`

## D. Interest-rate & term-structure models `📐`
20. Vasicek (1977) `📐` · 21. Cox, Ingersoll & Ross (1985) — CIR `📐` ·
22. Heath, Jarrow & Morton (1992) — HJM `📐` · 23. Hull & White (1990) `📐`

## E. Greeks, hedging & options mechanics `📐📊`
24. Leland (1985) — replication with transaction costs `📐`
25. Derman & Kani (1994) — implied tree `📐🖼`
26. Demeterfi et al. (1999) — *Variance Swaps* `📐`
27. Bakshi, Cao & Chen (1997) — empirical option-model performance `📊`
28. CBOE — the VIX construction white paper `📐📊`

## F. Market microstructure & execution `📐🖼`
29. Kyle (1985) — *Continuous Auctions and Insider Trading* `📐`
30. Glosten & Milgrom (1985) — bid-ask spread & adverse selection `📐`
31. Almgren & Chriss (2000) — *Optimal Execution* `📐🖼`
32. Obizhaeva & Wang (2013) — optimal trading with a limit-order book `📐`
33. Avellaneda & Stoikov (2008) — *HFT in a Limit Order Book* (market making) `📐`
34. Cartea, Jaimungal & Penalva (2015) — *Algorithmic and HF Trading* (key chapters) `📐🖼`

## G. Portfolio theory & risk `📐📊`
35. Markowitz (1952) — *Portfolio Selection* `📐📊`
36. Sharpe (1964) — CAPM `📐`
37. Kelly (1956) — the Kelly criterion `📐`
38. Artzner et al. (1999) — *Coherent Measures of Risk* `📐`
39. Rockafellar & Uryasev (2000) — Conditional VaR optimization `📐📊`

## H. Statistical arbitrage & mean reversion `📊📐`
40. Fama & French (1993) — 3-factor model `📊`
41. Gatev, Goetzmann & Rouwenhorst (2006) — *Pairs Trading* `📊📐`
42. Avellaneda & Lee (2010) — *Statistical Arbitrage in US Equities* `📐📊`
43. Ornstein-Uhlenbeck mean reversion — a canonical treatment `📐`

## I. Time series & regimes `📐📊`
44. Hamilton (1989) — Markov regime-switching `📐📊`
45. Kalman (1960) — the Kalman filter `📐`
46. Engle & Granger (1987) — cointegration `📐📊`

## J. Machine learning in finance & backtest rigor `📐📊🖼`
47. Gu, Kelly & Xiu (2020) — *Empirical Asset Pricing via ML* `📊🖼`
48. Buehler et al. (2019) — *Deep Hedging* `📐📊🖼`
49. López de Prado (2018) — *Advances in Financial ML* (labeling · CV · backtest overfitting) `📊🖼`
50. Bailey & López de Prado (2014) — *The Deflated Sharpe Ratio* `📐📊`

---
**Coverage** spans "what is MC simulation?" through modern ML-for-trading and **backtest
overfitting** rigor. The `📐📊🖼` items (SABR, CRR trees, Almgren-Chriss, Deep Hedging, López de
Prado) are the multimodal stress-tests — formulas, tables, and diagrams together. Prefer open PDFs /
preprints; ingest only key chapters of books you hold legally; the corpus is for a private knowledge
base, not redistribution.
</content>

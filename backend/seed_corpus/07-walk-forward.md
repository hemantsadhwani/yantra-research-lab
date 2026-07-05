# Walk-Forward Validation

**Walk-forward validation** is a method for testing a strategy that respects the arrow
of time. Instead of fitting parameters on the whole history at once (which overfits),
you repeatedly fit on a past window and test on the immediately following, unseen
window — then roll forward.

## The procedure
1. Split the timeline into consecutive segments.
2. **In-sample (train):** optimise parameters on an initial window.
3. **Out-of-sample (test):** apply those fixed parameters to the next window and record
   performance — this window was never used for fitting.
4. Roll the windows forward and repeat, stitching the out-of-sample results into one
   continuous track record.

Windows can be **anchored** (training start fixed, window grows) or **rolling**
(fixed-length window that slides).

## Why it is more honest
The concatenated out-of-sample performance approximates how the strategy would have
behaved if it had been re-tuned periodically and traded only on genuinely unseen data.
Consistent out-of-sample results across many folds give far more confidence than a
single impressive in-sample backtest, which is easy to overfit. Walk-forward is a
core defence against data snooping and complements strict backtesting parity.

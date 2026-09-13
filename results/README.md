# Measured results

Raw output from `research_lab/experiments/context_study.py` — the Day 6B context-engineering
study. Each JSON file is one full sweep at a given seed: three context constructions plus the
deterministic control, same engine, same baseline, same iteration budget.

| File | Seed |
|---|---|
| `context_study.json` | 0 |
| `context_study_seed7.json` | 7 |
| `context_study_seed13.json` | 13 |

Reproduce (needs `ANTHROPIC_API_KEY` and `pip install -e '.[llm]'`; costs a few cents per sweep):

```bash
python -m research_lab.experiments.context_study \
    --iterations 4 --variants 5 --seed 0 --include-heuristic \
    --json results/context_study.json
```

## Aggregate across the three seeds (model: claude-haiku-4-5)

| construction | mean input tokens | mean best score | range | mean Sharpe |
|---|---|---|---|---|
| everything | 3,966 | 37.9 | 35.0 – 42.7 | 2.27 |
| compacted | 1,815 | 36.2 | 31.3 – 39.4 | 2.04 |
| best_only | 1,494 | 32.1 | 28.0 – 38.4 | 1.80 |
| heuristic (no LLM) | 0 | 30.4 | 23.6 – 37.3 | 1.71 |

Baseline to beat: 4.9. Every construction clears it comfortably — the question is what the
*context* buys, not whether the loop works.

## What the numbers actually say

**Compaction is the efficient point.** It keeps 95% of the full-history score for 46% of the
input tokens. That is the whole context-engineering argument, measured on this system rather
than quoted.

**More context did win on average** — `everything` leads on mean score and Sharpe. The honest
version is that it *buys* something here, and that "cheapest is good enough" was not free.

**But the per-seed spread is wider than the gap between constructions.** Seed 0 ranks
everything > compacted > best_only; seed 7 reverses it entirely (compacted > best_only >
everything); seed 13 returns to everything first. With n=3 and a standard deviation of ~3.4
points against a mean gap of 1.7, **the ranking of `everything` vs `compacted` is not
established by this data.** What *is* established is the token ratio, which is stable to ±1%
across all three seeds. The right claim is "compaction held quality at half the tokens," not
"compaction wins."

**The LLM proposer beats the deterministic one** — 35.4 vs 30.4 mean — but not overwhelmingly,
and on seed 7 the heuristic (37.3) beat two of the three LLM constructions. The deterministic
path is free, instant (0.1s vs ~20s) and reproducible. That trade is the real finding: pay for
reasoning where the search space rewards it, and know what you are buying.

To settle the `everything` vs `compacted` ranking would need more seeds; it is left open rather
than overstated.

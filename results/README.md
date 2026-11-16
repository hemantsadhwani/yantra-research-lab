# Measured results

## Planted-edge benchmark (research bench, 16 Nov 2026)

`eval/planted_benchmark.py`. There are 20 synthetic markets with a known answer:
- 10 have a planted edge (5 trend, 5 mean-reversion), so the right verdict is promote.
- 10 are pure noise with the same volatility, so the right verdict is reject.

Each market comes with an idea in plain words. Seeds 1–20 are used here. Calibration used seeds 1000–1019 only.

| Arm | Edges recovered | Noise promoted | Trials | Cost | File |
|---|---|---|---|---|---|
| naive: grid search, promote best in-sample Sharpe ≥ 0.6 | 10/10 | **4/10** | 25,200 | $0 | `planted_benchmark_2026-11-16.json` |
| protocol: same grid, walk-forward + sealed 2-year holdout | 9/10 | 0/10 | 25,200 | $0 | same |
| bench, rule-based agents | 9/10 | 0/10 | 2,400 | $0 | `…_agents-offline.json` |
| bench, LLM agents **v1** | 6/10 | 0/10 | 2,297 | $0.34 | `…_agents-llm.json` |
| bench, LLM agents **v2** | **9/10** | **0/10** | **1,809** | **$0.34** (≈$0.017 a study, median 33 s) | `…_agents-llm_v2.json` |

LLM agents: Gemma 3 12B for intake and the report; DeepSeek V3.2 for the planner, researcher and critic. Both run on Bedrock in ap-south-1.

**What it shows.** Unguarded optimisation promotes noise 4 times in 10. The protocol stops that. The agents keep the protocol's verdicts and run 14× fewer trials. They do this by choosing templates, filters and rounds, and by stopping early.

**What it does not show.**
- Seed 5 is a planted edge that every guarded arm misses. It is too weak for the bar.
- Twenty markets is a small sample, and synthetic markets are cleaner than real ones.
- On real NIFTY 50 daily data, the protocol rejects all five template families. The bench agrees in its live study: 40 trials, $0.02, reject. That run is not stored in `results/`.

**Disclosures (also in each agents file).**
1. The looks penalty was added after an early rule-based smoke test promoted noise at benchmark seed 12. The penalty is OOS Sharpe bar = 0.4 + 0.1·log2(looks). It was set from first principles, not tuned.
2. v1's three misses (seeds 7–9) came from narrow first looks: the model opened with textbook RSI 14, and the critic stopped early.
3. v2 makes round 1 a code-run baseline: each planned template's full grid.
4. v2 was checked on calibration seeds first: 9/10 edges, 0/10 noise, 1,552 trials. It then ran once on seeds 1–20.
5. The change was prompted by v1's benchmark failures. Both files are kept.

Reproduce: `python -m eval.planted_benchmark [--agents offline|llm] [--tag v2]`. The `llm` arm needs AWS credentials with Bedrock access. `--calibration` runs seeds 1000–1019 into `.cache/`, never into `results/`.

## Context-engineering study (Day 6B)

Raw output from `research_lab/experiments/context_study.py` — the Day 6B context-engineering
study. Each JSON file is one full sweep at a given seed: three context constructions plus the
deterministic control, same engine, same baseline, same iteration budget.

These numbers were produced by the stdlib arm (`research_lab.run`) with the pre-gateway proposer,
which called the Anthropic SDK directly; the `llm_gateway/` provider seam landed on 2026-09-29,
and a re-run of the study through the gateway is pending.

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

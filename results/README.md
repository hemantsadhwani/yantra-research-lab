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

**Which model for which agent (calibration seeds 1000–1019, 17 Nov).** Model choice is tuning, so it
ran on calibration seeds only (`--calibration --models gemma|deepseek`; files in `.cache/`, not committed):

| Models | Edges | Noise | Trials | Cost (20 studies) | Median study |
|---|---|---|---|---|---|
| all Gemma 3 12B | 8/10 | 0/10 | 940 | $0.027 | 14 s, plus 1 study crashed on a malformed proposal |
| mix (Gemma intake/report, DeepSeek plan/research/critic) | 9/10 | 0/10 | 1,552 | $0.27 | 24 s |
| all DeepSeek V3.2 | 10/10 | 0/10 | 2,581 | $0.21 | 16 s |

The research roles stay on DeepSeek. Gemma alone is 10× cheaper, but it lost an edge and broke the schema once.
The mix and all-DeepSeek differ only in the intake model; 9 vs 10 is within noise at n = 20. The crash led to
a fix: bad model output now falls back to the rule policy and is counted (`agent_failures` in the verdict),
so a degraded study never looks clean.

Reproduce: `python -m eval.planted_benchmark [--agents offline|llm] [--tag v2]`. The `llm` arm needs AWS credentials with Bedrock access. `--calibration` runs seeds 1000–1019 into `.cache/`, never into `results/`.

## Learn from the ledger: rejection-sampling fine-tuning (19 Nov 2026)

`research_bench/ledger_ft/` has six parts:
1. A teacher (DeepSeek V3.2) runs bench studies on calibration seeds 1000+.
2. Code labels each researcher proposal (`label.py`).
3. Only verified wins go into a hashed training set (`dataset.py`).
4. Qwen2.5-3B-Instruct is QLoRA-trained on it locally on an RTX 3060 (`train_qlora.py`).
5. The tuned model is served locally as the researcher (`llm_gateway/hf_local_provider.py`).
6. It is evaluated once on benchmark seeds 1–20 (`evaluate.py --final`).

Guards: benchmark seeds are refused everywhere else, and each final arm can run only once. Every paid call reserves its worst-case cost against a hard cap (`spend.py`). Tests: `research_bench/tests/test_ledger_ft.py` (no GPU, network or AWS).

A **win** needs a right final verdict plus one of the following:
- **edge market:** the proposal's family passed walk-forward at the raised bar, or it stopped after an earlier family had cleared it;
- **noise market:** it stopped with zero new trials.

**Final eval, seeds 1–20, run once per arm.** All three arms use the same v2 setup: Gemma intake, DeepSeek planner, plan critic and critic. Only the researcher changes.

| Researcher | Edges | Noise promoted | Trials | Cost / study | Fallbacks | Refused by code | Median study | File |
|---|---|---|---|---|---|---|---|---|
| DeepSeek V3.2 (v2, 16 Nov) | 9/10 | 0/10 | 1,809 | $0.017 | 0 | 48 | 33 s | `planted_benchmark_2026-11-16_agents-llm_v2.json` |
| Qwen2.5-3B, untuned | 9/10 | 0/10 | **1,305** | $0.0072 | 1 | 81 | 141 s | `ledger_ft_2026-11-19_base.json` |
| Qwen2.5-3B + ledger QLoRA | 9/10 | 0/10 | 1,824 | $0.0076 | 0 | 38 | 195 s | `ledger_ft_2026-11-19_student.json` |

**What it shows.**
- **Verdicts:** a local 3B researcher, tuned or not, kept v2's verdicts on seeds 1–20 (9/10 edges, 0/10 noise).
- **Cost:** it cut cost per study by 55–58%, because the researcher calls cost $0.
- **Validity:** fine-tuning halved the proposals code refused, from 81 to 38. Valid JSON went from 33 calls plus 1 fallback to 35 calls with 0 fallbacks.

**What it does not show.**
- **Fine-tuning did not cut trials. That was the target KPI, and it failed.** The student ran 1,824 trials against 1,305 for the untuned model, about the same as its teacher (v2: 1,809).
- The untuned model's low count comes from bad proposals, not discipline. Code refused most of its experiments: only 28 of 77 ran, against 50 of 86 for the student.
- The student learned to imitate its teacher's valid refinements. It did not learn to stop.
- The label rewards finding a family that clears the bar, not finding it cheaply.
- The teacher set `stop` only 3 times in 670 proposals, so the set held only 2 noise-stop wins in 151.
- The cost cut belongs to local serving, not to fine-tuning: the untuned model gets the same cut.
- Studies are slower, because one local GPU serves the researcher calls one at a time.
- Twenty markets is a small sample. A 9 vs 9 tie says nothing about the edge rate.

**Collection, calibration seeds 1000–1431 (v2 setup, DeepSeek researcher; files in `.cache/ledger_ft/`).**
- **Studies:** 432, with 0 errors and 0 fallbacks.
- **Verdicts:** 168/216 edges, 3/216 noise promoted.
- **Yield:** 151 wins in 670 proposals, at $5.00.
- **Training set:** 151 records, SHA-256 `53d7b29c…de46`. Kinds: 84 trend, 65 meanrev, 2 noise.

The pilot gate (seeds 1000–1015) failed first. It projected $6.07 against a $5.00 cap, with a win rate of 0.19 against 0.20. Hemant raised the cap to $8 and chose to proceed. The win-rate test was overridden.

**Training.**
- **Setup:** 4-bit NF4 base, LoRA r=16 on all attention and MLP projections (29.9M trainable of 1.73B parameters shown in 4-bit), loss on the assistant turn only.
- **Data:** 136 train and 15 validation records, split by seed.
- **Schedule:** 3 epochs, 51 steps of 8 examples, lr 2e-4 cosine.
- **Run:** 78 minutes, with a peak of 10.3 GiB allocated. Windows spilled into shared memory, which slowed it.
- **Validation loss:** 1.042, then 0.630, 0.572 and 0.568.

**Smoke check before the final eval.** Calibration seeds 1900–1907, with every other role on the rule policy, at $0:

| Researcher | Edges | Noise | Trials / study |
|---|---|---|---|
| untuned | 3/4 | 0/4 | 161 |
| tuned | 3/4 | 0/4 | 156 |
| rule policy | 3/4 | 0/4 | 126 |

**Spend (ledger, list price):**

| Stage | Cost |
|---|---|
| pilot | $0.193 |
| collection | $4.812 |
| final eval, untuned | $0.144 |
| final eval, student | $0.153 |
| **total** | **$5.30** (cap $8) |

There were 3,391 paid calls. None failed, and none passed its reservation. Training and serving ran on the local GPU at $0.

**Next, not built.** Two changes could make the trials KPI movable:
- give the teacher the option to stop, plus the round's trial cap in its brief;
- add a label term that rewards clearing the bar with fewer trials.

Each needs a new calibration pilot first.

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

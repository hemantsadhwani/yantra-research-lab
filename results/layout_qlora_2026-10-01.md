# Layout SLM: QLoRA on real arXiv pages, 2026-10-01

**Claim:** Qwen2.5-1.5B-Instruct, QLoRA-tuned for about 15 minutes on one NVIDIA T4, labels the
layout of pages from **41 papers it never saw** at **0.978** (587/600), against 0.787 for always
answering `text` and 0.032 for the untuned model. It copies a deterministic rule; it does not beat it.

## Data

Dataset `87060948b499`, built by `slm_regime_classifier/build_layout_dataset.py` from the 426
arXiv q-fin PDFs the daily ingest job had put in `s3://yantra-research-lab-data/yantra-corpus/raw/`.
Up to 20 pages per paper, tables scanned on every page, 7,506 pages, 0 papers failed. Labels come
from `ingestion/layout_labels.derive_label` (a rule over the parser's counts, not human
annotation). Split by paper with a salted hash, so no paper is on both sides:

| split | papers | pages | labels |
|---|---:|---:|---|
| train | 344 | 6,022 | text 4,868 · mixed 891 · figure-heavy 241 · table-heavy 16 · scanned 6 |
| val | 41 | 741 | text 574 · mixed 133 · figure-heavy 33 · table-heavy 1 |
| test (locked) | 41 | 743 | text 586 · mixed 129 · figure-heavy 23 · table-heavy 5 |

Val and test are scored on a fixed 600-page sample each (natural label mix).

## Two runs, same data and model

Both: 4-bit nf4 base, LoRA r=16 on q/k/v/o (4.36 M trainable of 893 M), 1,000 steps, batch 8,
g4dn.xlarge (T4, fp16 compute), transformers 5.18, peft 0.21, bitsandbytes 0.50.

| | v1 | v2 (`@champion`) |
|---|---|---|
| learning rate | 1e-3 | 2e-4 |
| training rows | 3,000: text 1,846 · mixed 891 · figure 241 · table 16 · scanned 6 | 2,654: text 1,500 · mixed 891 · figure 241 · table 16 · scanned 6 |
| batches | round-robin over the 5 labels: each batch ~20% per label, so the 6 scanned pages recur constantly | shuffled: each batch follows the set's mix |
| gradient clipping | none | norm 1.0 |
| checkpoint | final weights (step 1000) | best on a 200-page val slice every 200 steps: step 400 |
| loss | 0.09 at step 700, **2.07 at step 900**, 0.54 at 1000 | stable; val slice 0.97 at 200, 1.00 from 400 on |
| **test accuracy** | **0.662** | **0.978** |
| val accuracy | 0.748 | 0.993 |

Test accuracy per label (correct / pages):

| label | pages | base | v1 | v2 |
|---|---:|---:|---:|---:|
| text | 472 | 0 | 375 | **472** |
| mixed | 104 | 0 | 14 | **92** |
| figure-heavy | 19 | 19 | 6 | **18** |
| table-heavy | 5 | 0 | 2 | **5** |
| scanned | 0 | – | – | – |

The base model answers `figure-heavy` for every page. v1 fell below the majority baseline: the
learning rate was too high for a 1.5B model (the loss spike, with no checkpoint selection to
recover from it), and round-robin batches taught it a world where every label is equally common,
so it mislabelled 97 of 472 `text` pages. The two training sets were close (1,846 vs 1,500 `text`
rows); the batching, not the sample, carried the prior. v2 fixed all three.

Latency: 152 ms per page (greedy, 6 new tokens, one page at a time) on the T4.

## What the numbers do not show

- That the model beats the rule. The rule is 100% on its own labels, in microseconds, at $0. The
  case for a model (ADR-0012) needs labels from a frontier model, which this run did not use.
- Anything about `table-heavy` (5 test pages) or `scanned` (0 test pages).
- Serving. The router's `slm` tier still calls Ollama through `llm_gateway`, not this adapter.

## Reproduce

On the dev GPU box (see `deploy/ec2/SESSION_LIFECYCLE.md`):

```bash
bash deploy/ec2/layout_session.sh          # v2 recipe is the default
LR=1e-3 SAMPLE=balanced BALANCED_FLAG=--balanced CLIP=0 SELECT_EVERY=0 bash deploy/ec2/layout_session.sh   # v1
```

Tracking: MLflow experiment `yantra-layout-slm`, registered model `layout-classifier` (v1 run
`83b7eeba6fbf497ab8ef3d7dec7a0de7`, v2 run `7e312cdcc5e04c33b0e3ddcb3f07ba77`), store and
artifacts under `s3://yantra-research-lab-data/ml/mlflow/`. Card: `slm_regime_classifier/adapter_card_dataset.md`.

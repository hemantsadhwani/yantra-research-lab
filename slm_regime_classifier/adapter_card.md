# Layout-label LoRA adapter card

Written by `python slm_regime_classifier/distill_layout.py` on 2026-09-30. The adapter itself
lives under `slm_regime_classifier/adapters/layout-smollm2-135m-instruct/` and is git-ignored.

| | |
|---|---|
| base model | `HuggingFaceTB/SmolLM2-135M-Instruct` |
| method | LoRA (r=16, alpha=32, dropout 0.05, targets q_proj, k_proj, v_proj, o_proj), CPU, fp32 |
| trainable params | 1,843,200 of 136,358,208 |
| data | 300 training examples, 60 held out; teacher = `layout_labels.derive_label` (free labels from the parser) |
| training | 127 steps, batch 4, lr 0.001, class-balanced batches, 1507.0 s (hit the 25-minute cap) |
| training labels | {'figure-heavy': 26, 'mixed': 64, 'scanned': 8, 'table-heavy': 24, 'text': 178} |
| loss | 3.7689 at step 1 to 0.1182 (mean of the last 25 steps) |
| machine | x86_64 CPU, 4 logical cores, torch 2.2.2, Python 3.12.4 |

## Held-out result (60 examples, greedy, 6 new tokens)

| model | accuracy | invalid replies | p50 latency per example | predictions |
|---|---:|---:|---:|---|
| base | 0.00 (0/60) | 60 | 1621 ms | {'invalid': 60} |
| LoRA-tuned | 0.87 (52/60) | 0 | 1319 ms | {'figure-heavy': 9, 'mixed': 12, 'scanned': 3, 'table-heavy': 3, 'text': 33} |

Held-out labels: {'figure-heavy': 3, 'mixed': 19, 'scanned': 2, 'table-heavy': 2, 'text': 34} (always answering the most common label scores
0.57). Held-out sources: {'silver': 19, 'synthetic': 41}.

What this shows: a 135M model can learn most of a deterministic five-way rule from a one-line
feature string on a laptop CPU. What it does not show: that it beats the rules backend (it is
distilled *from* those labels and cannot exceed them), or anything about real layout
understanding from pixels. QLoRA (4-bit) needs CUDA and was not run.

## Run history (hand-written, 2026-09-30)

| run | command | steps (cap) | tuned accuracy | what happened |
|---|---|---:|---:|---|
| 1 | `distill_layout.py` (shuffled, batch 8) | 40 of 300 (25-min cap hit) | 0.57 (34/60) | Learned the output format (0 invalid vs 60 for base) but collapsed to the majority class: 59 of 60 replies were `text`. 0.57 is exactly the always-`text` score |
| 2 | `distill_layout.py --balanced --batch 4` | 127 of 300 (25-min cap hit) | 0.87 (52/60) | This adapter. Class-balanced batches fixed the collapse |

For scale: the `rules` backend scores 0.92 on the same 60 held-out examples, in microseconds
and at $0. The tuned model needs about 1.3 s per page on this CPU. Both runs hit the 25-minute
cap: the dev Mac (Intel, 2 physical cores, 8 GB) was also running a VM and swapping, at about
38 s per batch-8 step in run 1 and 12 s per batch-4 step in run 2.

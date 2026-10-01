# Layout-label adapter card — dataset mode

Written by `python slm_regime_classifier/distill_layout.py --dataset ...` on 2026-10-01.
Dataset `87060948b499` (built by `build_layout_dataset.py`, split by paper, labels from
`layout_labels.derive_label`). The adapter lives under `slm_regime_classifier/adapters/layout-qwen2.5-1.5b-instruct-qlora/`
(git-ignored) and in MLflow run `7e312cdcc5e04c33b0e3ddcb3f07ba77`.

| | |
|---|---|
| base model | `Qwen/Qwen2.5-1.5B-Instruct` |
| method | QLoRA (4-bit nf4) r=16, alpha=32, targets q_proj, k_proj, v_proj, o_proj |
| trainable params | 4,358,144 of 892,974,592 |
| training set | 2654 rows from the train split, natural mix with no label above 0.5 of the set: {'figure-heavy': 241, 'mixed': 891, 'scanned': 6, 'table-heavy': 16, 'text': 1500} |
| training | 1000 steps, batch 8, lr 0.0002, grad clip 1.0, sample `capped` (max share 0.5), shuffled batches, 905.7 s |
| checkpoint | step 400 of 1000, best on a 200-row val slice: 200: 0.970, 400: 1.000, 600: 1.000, 800: 1.000, 1000: 1.000 |
| loss | 1.0441 at step 1 to 0.0046 (mean of the last 25 steps) |
| machine | x86_64, Tesla T4, torch 2.14.1+cu130, Python 3.13.15 |

| split | model | accuracy | invalid | p50 latency | per label (correct/n) |
|---|---|---:|---:|---:|---|
| val | base | 0.045 (27/600) | 0 | 156 ms | figure-heavy 27/27 · mixed 0/103 · table-heavy 0/1 · text 0/469 |
| val | tuned | 0.993 (596/600) | 0 | 153 ms | figure-heavy 26/27 · mixed 100/103 · table-heavy 1/1 · text 469/469 |
| test | base | 0.032 (19/600) | 0 | 155 ms | figure-heavy 19/19 · mixed 0/104 · table-heavy 0/5 · text 0/472 |
| test | tuned | 0.978 (587/600) | 0 | 152 ms | figure-heavy 18/19 · mixed 92/104 · table-heavy 5/5 · text 472/472 |

`val` and `test` are scored on their natural label mix (sampled to at most 600 rows each);
always answering the most common label would score 0.787 on test. `test` is the
locked split: quote it once per model, and tune nothing against it. The student learns the rule's
labels, so it cannot beat the rule; the numbers say how well a small model copies it on unseen papers.

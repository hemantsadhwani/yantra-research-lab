# Session lifecycle: launch, retrain, register, terminate

The dev GPU box is disposable. Everything that must outlive a session lives in S3 or GitHub, so
each session starts from a fresh box and ends with `terminate`. Written 2026-10-01 after the
first two retraining sessions; every command below was run that day.

## What survives a terminate

| Thing | Where it lives |
|---|---|
| Code, tests, this runbook | GitHub `hemantsadhwani/yantra-research-lab` |
| Raw arXiv PDFs (bronze, 426 on 2026-10-01) | `s3://yantra-research-lab-data/yantra-corpus/raw/` (written by the daily ingest job only) |
| Parsed page features (cache) | `s3://…/ml/silver/layout_features/<parser tag>/<paper>.json` |
| Datasets (train/val/test + manifest) | `s3://…/ml/datasets/layout/<version>/` |
| MLflow runs, registry, aliases | `s3://…/ml/mlflow/mlflow.db` (SQLite, pulled at start, pushed at end) |
| MLflow artifacts (adapter, card, code) | `s3://…/ml/mlflow/artifacts/` (written directly by MLflow) |
| What dies with the box | the OS disk: installed packages, Hugging Face model cache, local logs |

The box's role reads `yantra-corpus/*` and reads/writes `ml/*`; it cannot delete anything in S3
and cannot write the ingest job's folders (`deploy/ec2/iam/dev-box-s3-policy.json`).

## 1. Start (from nifty_dev, profile `yantra-launcher`)

```bash
cd ~/work/yantra-research-lab
bash deploy/ec2/launch.sh preflight                 # free: identity, GPU quota, role, AMI
TYPE=g6.xlarge DISK_GB=100 bash deploy/ec2/launch.sh launch --yes     # bills from here
```

Mumbai often has no g5/g6 capacity (2026-10-01: none in either zone for an hour). Try in order:
`g6.xlarge` → `g5.xlarge` → `g4dn.xlarge` (T4 16 GB; the code switches to fp16 there), each with
`AZ=ap-south-1a` and `AZ=ap-south-1b`. The fallback region `us-east-1` is allowed by the launcher
policy; its GPU quota was requested on 2026-10-01.

## 2. Bootstrap and train (on the box, in tmux)

```bash
ssh -i ~/.ssh/yantra-dev.pem ubuntu@<ip> "git clone https://github.com/hemantsadhwani/yantra-research-lab.git ~/work/yantra-research-lab && \
  tmux new -d -s run 'bash ~/work/yantra-research-lab/deploy/ec2/bootstrap.sh > ~/bootstrap.log 2>&1 && \
  bash ~/work/yantra-research-lab/deploy/ec2/layout_session.sh > ~/session.log 2>&1'"
```

`layout_session.sh` does, in order: install the training extras → pull `mlflow.db` from S3 →
build the dataset (cached features make a rebuild take seconds; same data gives the same
version hash) → QLoRA with val-slice checkpoint selection → score base and tuned on `val` and the
locked `test` split → log the run and register a new version with alias `candidate` → push
`mlflow.db` to S3 (also on failure). Override with env vars, e.g. `STEPS=200 MAX_PAPERS=40` for a
smoke run. Before a long run, do a 20-step smoke run first: two bugs on 2026-10-01 would each
have wasted a full session.

Timings on a T4 (g4dn.xlarge), 2026-10-01: bootstrap ~4 min, dataset from cache ~10 s (first
parse of 426 papers: ~8 min), 1000 steps ~15 min, eval of 1200 pages ~3 min.

## 3. Review and promote (human)

Read `slm_regime_classifier/adapter_card_dataset.md`. Promote only if the tuned `test` accuracy
beats both the majority baseline and the current champion on the same dataset version, and the
per-label rows show no collapsed label. On the box, before the session ends:

```bash
MLFLOW_TRACKING_URI=sqlite:///$HOME/work/yantra-research-lab/mlflow.db .venv/bin/python -c \
  "from mlflow import MlflowClient as C; C().set_registered_model_alias('layout-classifier', 'champion', '<version>')"
aws s3 cp mlflow.db s3://yantra-research-lab-data/ml/mlflow/mlflow.db
```

(2026-10-01, v2 was promoted from nifty_dev, which has no MLflow installed: `mlflow.db` was backed
up to `ml/mlflow/backups/`, the alias row was inserted with sqlite3, and the file pushed back.)

## 4. End

```bash
scp -i ~/.ssh/yantra-dev.pem ubuntu@<ip>:work/yantra-research-lab/slm_regime_classifier/adapter_card_dataset.md \
  slm_regime_classifier/                            # the committed record of the run
bash deploy/ec2/launch.sh terminate --yes           # box and disk gone; nothing else is touched
```

Check first that the session log ends with `pushed mlflow.db` and `EXIT=0`. Terminate removes the
idle-stop alarm too. Cost of a full retraining session on a T4: about $0.30–0.70.

## Model versions so far

| Version | Alias | Test (600 pages, 41 unseen papers) | Majority baseline | Notes |
|---|---|---:|---:|---|
| v1 | — (rejected) | 0.662 | 0.787 | lr 1e-3, class-balanced batches: loss spike at step 900, over-predicted rare labels |
| v2 | `champion` | 0.978 | 0.787 | lr 2e-4, grad clip 1.0, natural mix with `text` capped at 50%, best of 5 checkpoints on a val slice (step 400) |

#!/usr/bin/env bash
# One GPU session for the layout SLM, on the dev box (run in tmux; logs to stdout):
#   install the training extras -> pull MLflow state from S3 -> build the dataset from S3 bronze ->
#   QLoRA train + eval (val + locked test) -> log + register in MLflow -> push MLflow state to S3.
#
#   bash deploy/ec2/layout_session.sh                      # full run
#   MAX_PAPERS=40 STEPS=200 bash deploy/ec2/layout_session.sh   # quick smoke run
#
# Credentials: the instance role only (Bedrock + S3 corpus read + ml/ read/write). Nothing here
# deletes anything in S3. MLflow keeps its run database in mlflow.db, synced to
# s3://$BUCKET/ml/mlflow/mlflow.db, and its artifacts (adapter, card, manifest) directly in
# s3://$BUCKET/ml/mlflow/artifacts, so the box itself can be terminated after the session.
set -euo pipefail

BUCKET="${DATA_BUCKET:-yantra-research-lab-data}"
MODEL="${MODEL:-Qwen/Qwen2.5-1.5B-Instruct}"
MAX_PAPERS="${MAX_PAPERS:-0}"; MAX_PAGES="${MAX_PAGES:-20}"; PARSE_CAP="${PARSE_CAP:-30}"
STEPS="${STEPS:-1000}"; BATCH="${BATCH:-8}"; MAX_TRAIN="${MAX_TRAIN:-3000}"; TRAIN_CAP="${TRAIN_CAP:-45}"
# v2 defaults (v1 used lr 1e-3 + class-balanced batches: loss spiked at step 900, test 0.662 < 0.787 majority)
LR="${LR:-2e-4}"; SAMPLE="${SAMPLE:-capped}"; MAX_SHARE="${MAX_SHARE:-0.5}"; CLIP="${CLIP:-1.0}"
SELECT_EVERY="${SELECT_EVERY:-200}"; BALANCED_FLAG="${BALANCED_FLAG:-}"   # set to --balanced for round-robin batches
REGISTER="${REGISTER:-layout-classifier}"
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
export AWS_REGION="${AWS_REGION:-ap-south-1}" AWS_DEFAULT_REGION="${AWS_REGION:-ap-south-1}"
export MLFLOW_TRACKING_URI="sqlite:///$REPO/mlflow.db"
export MLFLOW_ARTIFACT_ROOT="s3://$BUCKET/ml/mlflow/artifacts"
export MLFLOW_EXPERIMENT_NAME="${MLFLOW_EXPERIMENT_NAME:-yantra-layout-slm}"
export ANTHROPIC_API_KEY= LOGFIRE_TOKEN=   # nothing in this session calls an LLM API
cd "$REPO"
PY=.venv/bin/python
log() { printf '\n==> [%s] %s\n' "$(date +%H:%M:%S)" "$*"; }

log "training extras (slm + mlflow + 4-bit + parser)"
.venv/bin/pip install -q -e ".[slm,dev]" bitsandbytes accelerate "pymupdf>=1.24,<1.29" boto3
$PY -c "import torch; assert torch.cuda.is_available(), 'no CUDA'; print('cuda', torch.cuda.get_device_name(0))"

log "MLflow state from S3 (first session: none yet)"
aws s3 cp "s3://$BUCKET/ml/mlflow/mlflow.db" mlflow.db 2>/dev/null && echo "pulled mlflow.db" || echo "no mlflow.db in S3 yet"
push_mlflow() { [[ -f mlflow.db ]] && aws s3 cp mlflow.db "s3://$BUCKET/ml/mlflow/mlflow.db" --only-show-errors \
                && echo "pushed mlflow.db to s3://$BUCKET/ml/mlflow/"; }
trap push_mlflow EXIT   # runs even if training fails, so finished runs are never lost

log "dataset from s3://$BUCKET/yantra-corpus/raw/ (cap ${PARSE_CAP} min)"
$PY slm_regime_classifier/build_layout_dataset.py --max-papers "$MAX_PAPERS" --max-pages "$MAX_PAGES" \
  --cap-minutes "$PARSE_CAP" | tee /tmp/dataset.log
[[ ${PIPESTATUS[0]} -eq 0 ]] || { echo "dataset build failed; not training"; exit 1; }
DS=$(sed -n 's/^local: //p' /tmp/dataset.log)
[[ -n "$DS" && -d "$DS" ]] || { echo "dataset build did not report a directory"; exit 1; }

log "QLoRA $MODEL on $(basename "$DS") (steps $STEPS, cap ${TRAIN_CAP} min)"
$PY slm_regime_classifier/distill_layout.py --dataset "$DS" --model "$MODEL" --qlora $BALANCED_FLAG \
  --steps "$STEPS" --batch "$BATCH" --lr "$LR" --max-train "$MAX_TRAIN" --sample "$SAMPLE" --max-share "$MAX_SHARE" \
  --clip "$CLIP" --select-every "$SELECT_EVERY" --cap-minutes "$TRAIN_CAP" --register "$REGISTER"

log "done"

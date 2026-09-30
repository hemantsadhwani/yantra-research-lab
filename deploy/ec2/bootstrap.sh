#!/usr/bin/env bash
# Dev box bootstrap for yantra-research-lab + agentic-reporting on Ubuntu 24.04 (x86_64 or arm64).
# Idempotent. Usage: bash deploy/ec2/bootstrap.sh [--gpu]
#   --gpu   also install the NVIDIA driver + CUDA toolkit (for the QLoRA path). Reboot once afterwards.
# Never run this on the trading system's instances.
set -euo pipefail

GPU=0; [[ "${1:-}" == "--gpu" ]] && GPU=1
WORK="${WORK:-$HOME/work}"
YANTRA_REPO="${YANTRA_REPO:-https://github.com/hemantsadhwani/yantra-research-lab.git}"
REPORTING_REPO="${REPORTING_REPO:-https://github.com/hemantsadhwani/agentic-reporting.git}"

log() { printf '\n==> %s\n' "$*"; }

log "base packages"
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
  build-essential curl git jq make unzip ca-certificates gnupg lsb-release tmux gh \
  software-properties-common tesseract-ocr poppler-utils

log "python 3.13"
if ! command -v python3.13 >/dev/null; then
  sudo add-apt-repository -y ppa:deadsnakes/ppa
  sudo apt-get update -qq
  sudo apt-get install -y -qq python3.13 python3.13-venv python3.13-dev
fi

log "docker"
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER"
fi

log "kubectl + kind"
ARCH=$(dpkg --print-architecture)   # amd64 | arm64
if ! command -v kubectl >/dev/null; then
  KV=$(curl -fsSL https://dl.k8s.io/release/stable.txt)
  sudo curl -fsSLo /usr/local/bin/kubectl "https://dl.k8s.io/release/${KV}/bin/linux/${ARCH}/kubectl"
  sudo chmod +x /usr/local/bin/kubectl
fi
if ! command -v kind >/dev/null; then
  sudo curl -fsSLo /usr/local/bin/kind "https://kind.sigs.k8s.io/dl/latest/kind-linux-${ARCH}"
  sudo chmod +x /usr/local/bin/kind
fi

log "ollama (local models; private mode)"
command -v ollama >/dev/null || curl -fsSL https://ollama.com/install.sh | sh

log "aws cli (for the instance role / bedrock checks)"
if ! command -v aws >/dev/null; then
  case "$ARCH" in amd64) A=x86_64;; arm64) A=aarch64;; esac
  curl -fsSLo /tmp/awscli.zip "https://awscli.amazonaws.com/awscli-exe-linux-${A}.zip"
  (cd /tmp && unzip -q -o awscli.zip && sudo ./aws/install --update)
fi

if [[ $GPU -eq 1 ]]; then
  log "NVIDIA driver + CUDA toolkit (reboot once after this)"
  sudo apt-get install -y -qq ubuntu-drivers-common
  sudo ubuntu-drivers install || true
  sudo apt-get install -y -qq nvidia-cuda-toolkit || true
fi

log "repos"
mkdir -p "$WORK"
for pair in "yantra-research-lab|$YANTRA_REPO" "agentic-reporting|$REPORTING_REPO"; do
  name="${pair%%|*}"; url="${pair##*|}"
  if [[ -d "$WORK/$name/.git" ]]; then git -C "$WORK/$name" pull --ff-only; else git clone -q "$url" "$WORK/$name"; fi
done

log "venvs + offline acceptance"
cd "$WORK/yantra-research-lab"
[[ -d .venv ]] || python3.13 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -e ".[all]"
if [[ $GPU -eq 1 ]]; then .venv/bin/pip install -q -e ".[slm]" bitsandbytes || true; fi
ANTHROPIC_API_KEY= LOGFIRE_TOKEN= .venv/bin/python -m pytest -q | tail -1
ANTHROPIC_API_KEY= LOGFIRE_TOKEN= .venv/bin/python -m eval.run_gate --arm both | tail -2

cd "$WORK/agentic-reporting"
[[ -d .venv ]] || python3.13 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -e ".[all]"
ANTHROPIC_API_KEY= LOGFIRE_TOKEN= .venv/bin/python -m pytest -q | tail -1
ANTHROPIC_API_KEY= LOGFIRE_TOKEN= .venv/bin/python -m eval.report_eval --fake | tail -1

log "bedrock check (instance role)"
if aws sts get-caller-identity >/dev/null 2>&1; then
  aws sts get-caller-identity --output text
  aws bedrock list-foundation-models --region "${AWS_REGION:-ap-south-1}" \
    --by-provider anthropic --query 'modelSummaries[].modelId' --output text 2>/dev/null | tr '\t' '\n' | head -5 \
    || echo "bedrock list failed: enable model access in the console and check the role policy"
else
  echo "no AWS identity: attach the instance profile from deploy/ec2/iam/bedrock-dev-role-policy.json"
fi

log "done. Next: LLM_PROVIDER=bedrock AWS_REGION=ap-south-1 LLM_MODEL=apac.anthropic.claude-haiku-4-5-20251001-v1:0 make demo-bedrock   (yantra)"
echo "     docker group: log out and back in once so 'docker' works without sudo."

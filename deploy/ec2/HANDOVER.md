# Handover: running both repos on the AWS dev box

Written 30 Sep 2026 for whoever pulls `yantra-research-lab` and `agentic-reporting` onto an EC2
instance. Everything below is either committed code with a proving command, or a task list.
No secrets, no private data. The trading system is a separate private repo and is out of scope.

## 1. Instance choice

| Phase | Instance | Why | Cost (us-east-1, on-demand) |
|---|---|---|---|
| **Training and benchmarks** (first) | `g6.xlarge` (L4 24 GB, 4 vCPU, 16 GB) or `g5.xlarge` (A10G 24 GB) | QLoRA on 0.5B–8B models fits in 24 GB with 4-bit weights; vLLM 7B–8B serving benchmark; Ollama 7B at speed | ~$0.80/h (g6) · ~$1.00/h (g5) · spot ~40% of that |
| **Inference, serving, dev** (later) | `g4dn.xlarge` (T4 16 GB) when a local model must run; otherwise `t3.large` / `m7i.large` | 7B models in 4-bit serve fine on a T4; everything else is CPU | ~$0.53/h (g4dn) · ~$0.08–0.10/h (CPU) |

- AMI: **Ubuntu 24.04 Deep Learning Base (NVIDIA driver)** for the GPU box, plain Ubuntu 24.04 for CPU.
  With the DL AMI, skip `--gpu` in the bootstrap.
- Disk: 200 GB gp3 (model weights, Docker images, MLflow runs).
- Region: `us-east-1` (Bedrock has every Anthropic model; GPU capacity is best). Mumbai works via
  cross-region inference profiles if data residency matters for a demo.
- IAM: instance profile from `deploy/ec2/iam/bedrock-dev-role-policy.json`. No IAM user keys.
- Security group: SSH from one IP. Nothing else inbound. `ssh -L` for UIs.
- **Stop the GPU box when idle.** Set a CloudWatch alarm: CPU < 5% for 60 min → stop.

## 2. First ten minutes on the box

```bash
git clone https://github.com/hemantsadhwani/yantra-research-lab.git ~/work/yantra-research-lab
bash ~/work/yantra-research-lab/deploy/ec2/bootstrap.sh        # clones agentic-reporting too, runs both acceptances
# log out and in once (docker group), then:
cd ~/work/yantra-research-lab && LLM_PROVIDER=bedrock AWS_REGION=us-east-1 make demo-bedrock
```

Expected: yantra `pytest` green, `EVAL-GATE PASS` on both arms; agentic-reporting `pytest` green,
`REPORT-EVAL PASS`, `SCHEMA-EVAL PASS`; `demo-bedrock` prints a `proposer: bedrock/...` line.
If Bedrock fails: enable model access in the console (Anthropic → Claude Haiku 4.5) and confirm the
instance profile with `aws sts get-caller-identity`.

## 3. What is built (pull and run; nothing to write)

**yantra-research-lab** — `make` targets and proving commands are in `CLAUDE.md` and `ROADMAP.md`.
LangGraph arm with SQLite checkpoints and a human interrupt · MCP engine · provider gateway
(Anthropic / Bedrock / Ollama) · three-layer memory · veto-only judge · budgets · Logfire spans ·
guardrails with a measured leak rate · CI with eval gates on both arms · Docker, Compose, kustomize,
kind · FAISS alternate retriever · RAGAS-style eval · MLflow tracking · page-layout router
(rules / slm / frontier) with its eval.

**agentic-reporting** — `make demo`, `make eval`, `make demo-ask`. Spec-as-code reports over
read-only SQL · deterministic number checker · human publish gate · audit table · provider-agnostic
with a tested private mode · schema graph for question → SQL · CronJob + approver pod on Kubernetes.

## 4. What the GPU box is for (in order; each leaves a file in `results/`)

| # | Task | Command / where | Done when |
|---|---|---|---|
| 1 | **Real Bedrock runs** (were only fake-tested on the Mac) | yantra: `make demo-bedrock`, `LLM_PROVIDER=bedrock make judge-eval`, `python -m eval.ragas_eval --provider bedrock`, `YANTRA_LAYOUT_BACKEND=frontier python -m eval.layout_eval` · agentic-reporting: `make demo-bedrock` | each prints a provider line naming `bedrock/…`; results files updated with real numbers; cost lines pasted |
| 2 | **QLoRA layout classifier** (the honest QLoRA keyword) | `pip install -e ".[slm]" bitsandbytes` then `python -m slm_regime_classifier.distill_layout --qlora --model Qwen/Qwen2.5-1.5B-Instruct` | `slm_regime_classifier/adapter_card.md` shows base vs tuned accuracy and latency; adapter saved (git-ignored) |
| 3 | **SLM backend with a real model** | `ollama pull qwen2.5:1.5b && YANTRA_LAYOUT_BACKEND=slm python -m eval.layout_eval` | `results/layout_*.md` has real rows: accuracy, agreement with frontier, $/1k pages, p50/p95 |
| 4 | **vLLM serving benchmark** | `pip install vllm`; serve `Qwen/Qwen2.5-7B-Instruct-AWQ`; point `OLLAMA_HOST`-equivalent (OpenAI-compatible) at it — add an `openai_compatible` provider to `llm_gateway/` if not present (small, mirrors `ollama_provider.py`) | table: tokens/s, p50/p95 at 1/4/16 concurrent, vs Ollama on the same box |
| 5 | **Private mode with a real local model** | agentic-reporting: `make demo-private`; yantra: `docker compose --profile private up` | published report from `ollama` with the repair count noted; README "no real local-model run shown" line removed |
| 6 | **MLflow server** (optional) | `mlflow server --backend-store-uri sqlite:///mlflow.db --host 127.0.0.1` and `MLFLOW_TRACKING_URI=http://127.0.0.1:5000` for all evals | runs from 1–4 visible in one UI; screenshot in `results/` |
| 7 | **Register the adapter** (after 2) | `mlflow.register_model` in `distill_layout.py --register` | model registry has one version with a stage |

Then move to the CPU/T4 box for anything that only serves or demos.

## 5. Claims discipline on the box

Every number written to `results/` names the provider and model that produced it, the date, and the
command. Fake-provider runs are labelled as harness checks. Nothing in a README says "production"
about the box. "Verified on an AWS dev instance" is the phrase.

## 6. Not on the box

Real `.env` keys, the trading system, any P&L or market-data files, customer data of any kind.

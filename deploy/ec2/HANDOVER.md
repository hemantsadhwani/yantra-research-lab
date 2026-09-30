# Handover: running both repos on the AWS dev box

Written 30 Sep 2026 for whoever pulls `yantra-research-lab` and `agentic-reporting` onto an EC2
instance. Everything below is either committed code with a proving command, or a task list.
No secrets, no private data. The trading system is a separate private repo and is out of scope.

## 0. Which box (decided 30 Sep 2026)

**Not `nifty_dev`.** That c7g.2xlarge is the trading system's intraday monitor host (docs/MONITOR_HOST_SETUP.md
in the private bot repo): it needs its 16 GB during market hours, runs Amazon Linux 2023 (this bootstrap is
Ubuntu), and holds the bot's `key_secrets/`. Public-repo work, Docker and GPU jobs go on their own instance.

**Region: ap-south-1 (Mumbai)**, where the account already lives. Two consequences:
- GPU quota: new accounts start at 0 vCPU for G instances. Service Quotas → EC2 → "Running On-Demand G and VT
  instances" → request 8 (and "All G and VT Spot Instance Requests" → 8 for spot). Can take hours to a day.
- Bedrock model ID: the code defaults to the **US** inference profile (`us.anthropic.claude-haiku-4-5-20251001-v1:0`),
  which does not route from Mumbai. On the box set `AWS_REGION=ap-south-1` and
  `LLM_MODEL=apac.anthropic.claude-haiku-4-5-20251001-v1:0` (or the `global.` profile if the console lists it).
  Enable model access for Claude Haiku 4.5 in the ap-south-1 Bedrock console first. The IAM policy already covers
  `apac.` and `global.` profiles.

| Phase | Mumbai choice | Notes |
|---|---|---|
| Training, benchmarks | `g5.xlarge` (A10G 24 GB, 4 vCPU, 16 GB RAM); `g6.xlarge` (L4) if the console offers it | stop between sessions; spot if quota allows |
| Serving, demos, Bedrock-only evals | `t4g.large` or `c7g.large` (Graviton, ARM) | everything in both repos runs on arm64; ~$0.05–0.09/h |
| Serving a local 7B model | `g4dn.xlarge` (T4 16 GB) | only if a demo must run with no vendor API |

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
cd ~/work/yantra-research-lab && LLM_PROVIDER=bedrock AWS_REGION=ap-south-1 LLM_MODEL=apac.anthropic.claude-haiku-4-5-20251001-v1:0 make demo-bedrock
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

## 7. Launch the box (from nifty_dev or any shell) — full runbook

### 7a. Owner, once, in the AWS console (admin login)

1. **Bedrock model access**, region ap-south-1: enable *Anthropic Claude Haiku 4.5* (Sonnet optional).
2. **Role for the box**: IAM → Roles → Create → trusted entity *AWS service: EC2* → name `yantra-dev-bedrock`
   → add an inline policy pasted from `deploy/ec2/iam/bedrock-dev-role-policy.json`. (The console also
   creates the instance profile with the same name.)
3. **Launcher login**: IAM → Users → Create `claude-dev-launcher` (no console access) → inline policy pasted from
   `deploy/ec2/iam/launcher-policy.json` → Security credentials → Create access key (CLI).
4. **Store it on nifty_dev yourself** (never paste keys into a chat or a file in a repo):
   ```bash
   aws configure --profile yantra-launcher      # region: ap-south-1, output: json
   ```

### 7b. The launch, step by step (`deploy/ec2/launch.sh`)

```bash
git clone https://github.com/hemantsadhwani/yantra-research-lab.git ~/work/yantra-research-lab   # separate from the bot checkout
cd ~/work/yantra-research-lab
bash deploy/ec2/launch.sh preflight          # identity, GPU quota, AZs offering g5.xlarge, role, AMI   (free)
bash deploy/ec2/launch.sh quota 8            # only if the quota is below 4; then wait for approval    (free)
bash deploy/ec2/launch.sh plan               # exactly what will be created                             (free)
bash deploy/ec2/launch.sh launch --yes       # key pair, SSH-only security group, box, idle-stop alarm   (BILLS)
bash deploy/ec2/launch.sh ssh                # log in as ubuntu
```

Options (env): `TYPE=g6.xlarge`, `MARKET=spot`, `DISK_GB=300`, `EXTRA_SSH_CIDR=<home IP>/32` so the laptop can
SSH too. Day to day: `status`, `stop`, `start` (the public IP changes on each start), `resize t4g.large --yes`
after training. The script and the IAM policy both act only on resources tagged `purpose=dev-public-repos`.

### 7c. On the box, once

```bash
git clone https://github.com/hemantsadhwani/yantra-research-lab.git ~/work/yantra-research-lab
tmux new -s boot 'bash ~/work/yantra-research-lab/deploy/ec2/bootstrap.sh 2>&1 | tee ~/bootstrap.log'
# then log out and in once (docker group)
curl -fsSL https://claude.ai/install.sh | bash        # Claude Code; log in when it asks
gh auth login                                         # fine-grained token: yantra-research-lab + agentic-reporting,
                                                      # Contents: read/write, Workflows: read/write, nothing else
```

## 8. Rules for any agent working here

- On **nifty_dev**: never read or change `~/index-options-trading-bot`, the `~/shadow_bt*` worktrees, the crontab,
  or `key_secrets/`. No Docker, no model downloads, no heavy installs there: it is the live monitor host
  (09:00–15:45 IST). Its only job in this handover is to run `launch.sh`.
- Any command that bills (`launch`, `resize`, `start` of a GPU type) or destroys (`terminate`) runs only after the
  owner says yes in the chat. Never `terminate` unless asked in those words.
- On the **GPU box**: Bedrock via the instance role only; every LLM command carries `--max-usd`; total Bedrock spend
  for the whole task list stays under **$5** unless the owner raises it.
- `git pull --rebase` before every push: yantra's daily ingest job commits to `main` on GitHub.
- Every result names provider, model, date and command. Fake-provider results stay labelled as harness checks.

## 9. Prompts to paste

### Prompt 1 — Claude Code on **nifty_dev** (launches the box)

```text
You are on nifty_dev, the live trading system's monitor host. Your only job is to launch a separate GPU dev box
with the committed launcher script, then bootstrap it. Hard rules: do not read, list or modify
~/index-options-trading-bot, ~/shadow_bt*, the crontab or any key_secrets folder; no Docker, no pip installs, no
model downloads on this machine; use only the AWS profile "yantra-launcher"; never print or store credentials.

1. If ~/work/yantra-research-lab exists, `git pull --rebase` there; else clone
   https://github.com/hemantsadhwani/yantra-research-lab.git into ~/work/yantra-research-lab.
   Read deploy/ec2/HANDOVER.md sections 0, 1, 7 and 8, and deploy/ec2/launch.sh.
2. Run `bash deploy/ec2/launch.sh preflight` and show me the output.
   - If the G/VT on-demand quota is below 4: run `bash deploy/ec2/launch.sh quota 8`, tell me, and stop here.
   - If the role or model access is missing: tell me the exact console step from section 7a and stop.
3. Run `bash deploy/ec2/launch.sh plan`, show it to me, and WAIT until I reply "yes launch".
4. Run `bash deploy/ec2/launch.sh launch --yes` (add EXTRA_SSH_CIDR=<my home IP>/32 if I gave one).
5. Bootstrap the box over SSH without keeping a session open:
   ssh -i ~/.ssh/yantra-dev.pem -o StrictHostKeyChecking=accept-new ubuntu@<ip> \
     "git clone https://github.com/hemantsadhwani/yantra-research-lab.git ~/work/yantra-research-lab && \
      tmux new -d -s boot 'bash ~/work/yantra-research-lab/deploy/ec2/bootstrap.sh > ~/bootstrap.log 2>&1'"
   Poll `tail -5 ~/bootstrap.log` over SSH every few minutes until it prints "done". Report the acceptance lines
   (pytest summaries, EVAL-GATE, REPORT-EVAL, SCHEMA-EVAL) and the Bedrock check.
6. Give me: the SSH command, how to stop the box (`bash deploy/ec2/launch.sh stop`), and remind me to install
   Claude Code and run `gh auth login` on the box (section 7c) before Prompt 2. Do not terminate anything.
```

### Prompt 2 — Claude Code on the **GPU box**, in `~/work/yantra-research-lab`

```text
You are on the yantra dev GPU box (g5/g6, Ubuntu, ap-south-1). Read CLAUDE.md, deploy/ec2/HANDOVER.md (all of it,
especially sections 4, 5 and 8), then ../agentic-reporting/CLAUDE.md. Work through HANDOVER section 4, tasks 1 to 7,
in order. Environment for every LLM call:
  export LLM_PROVIDER=bedrock AWS_REGION=ap-south-1 LLM_MODEL=apac.anthropic.claude-haiku-4-5-20251001-v1:0
Credentials come from the instance role only. Put --max-usd on every LLM run; keep total Bedrock spend under $5
and print a running total after each task.

For each task:
- run it, write or update results/<task>_<YYYY-MM-DD>.md with provider, model, date, exact command, numbers and cost;
- update README / ROADMAP / adapter_card only where a real result replaces a "not run" or fake-only line;
- keep all tests and both eval gates green; stdlib hash of
  `python -m research_lab.run --iterations 2 --variants 3 --seed 3 | md5sum` must stay b9af72166a5ad9b8d015c808625e1fb4;
- commit (message ends with the Co-Authored-By line the session gives you), `git pull --rebase`, push.
Long jobs (QLoRA, vLLM) run inside tmux with logs under ~/logs/. If a task fails twice, write down exactly why in
its results file, commit that, and move on. After task 7, give me a table of every task: done or not, the headline
number, cost, and the file to open. Then remind me to stop the box from nifty_dev.
```

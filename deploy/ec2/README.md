# deploy/ec2 — a development box for both public repos

A **separate** dev instance. Never the trading system's EC2 boxes: those are production and
must not carry a public repo, Docker, or a GPU workload.

## What the box is for

| Need | Why not the Mac | Instance | Cost while on |
|---|---|---|---|
| Claude on Bedrock via an **instance role** (no keys on disk) | works from the Mac too, but the role is the enterprise pattern | any | — |
| **QLoRA** for real (4-bit needs CUDA) | no NVIDIA GPU | `g5.xlarge` (A10G 24 GB) or `g6.xlarge` (L4) | ~$1.0/h on-demand, ~$0.4/h spot |
| vLLM serving benchmark, 7B–8B local models at speed | Intel Mac, no GPU | same GPU box | same |
| kind / Kubernetes with room, ingestion runs, MLflow server | 2-CPU Colima VM | `m7i.large` / `t3.large` | ~$0.10/h |

Stop the instance when idle. A GPU box left on for a week costs more than the whole sprint's API spend.

## Bedrock access

1. Model access: Bedrock console → Model access → enable **Anthropic Claude Haiku 4.5** (and Sonnet if
   wanted) in the region you will use. `us-east-1` has everything; `ap-south-1` (Mumbai) serves Claude via
   cross-region inference profiles — check the console.
2. IAM role for the instance: `iam/bedrock-dev-role-policy.json` (invoke only, scoped to the Anthropic
   model ARNs and inference profiles; no `bedrock:*`). Attach it as an instance profile.
3. On the box, no `AWS_ACCESS_KEY_ID` at all. The SDK reads the role. `LLM_PROVIDER=bedrock AWS_REGION=us-east-1`.

## One-command setup

```bash
# on a fresh Ubuntu 24.04 instance (as ubuntu), after cloning either repo:
bash deploy/ec2/bootstrap.sh            # python 3.13, docker, kind, kubectl, ollama, both repos, venvs, tests
bash deploy/ec2/bootstrap.sh --gpu      # + NVIDIA driver, CUDA toolkit, bitsandbytes; enables the QLoRA path
```

The script is idempotent: rerun it after a reboot or a pull. It ends by running the offline acceptance of
both repos (`make test` / `make gate` / `make eval`) so a bad box is obvious in the first ten minutes.

## Security basics for a dev box that holds public code only

- No `.env` with real keys. Bedrock via the role; Anthropic direct only if a key is exported for one shell.
- Security group: SSH from your IP only. No inbound 80/443/11434. Use `ssh -L` for the MLflow UI, Ollama
  and the kind Ingress.
- Ubuntu with unattended upgrades on; an instance profile, not an IAM user.
- Tag the instance `purpose=dev-public-repos` so nobody mistakes it for the trading control plane.

# yantra-research-lab

> **Autonomous multi-agent platform for quant strategy research.** Agents propose strategy
> variants, backtest each, judge them on risk-adjusted returns, rank, remember what worked,
> and iterate — bounded by a budget, with a human-approval gate before promotion.

![tier](https://img.shields.io/badge/tier--1-runnable-brightgreen)
![python](https://img.shields.io/badge/python-3.12-blue)
![tests](https://img.shields.io/badge/tests-16%20passing-brightgreen)
![eval--gate](https://img.shields.io/badge/eval--gate-passing-success)
![deps](https://img.shields.io/badge/tier--1%20deps-stdlib%20only-success)
![license](https://img.shields.io/badge/license-MIT-lightgrey)

Runs on a **public synthetic backtest engine** (zero proprietary IP) so anyone can reproduce it.
The production version drives a private engine — referenced here only in the abstract.

## Quickstart (no dependencies)

```bash
git clone <this-repo> && cd yantra-research-lab
python -m research_lab.run            # 4 iterations × 5 variants
python -m research_lab.run --iterations 6 --variants 6 --seed 7
python -m research_lab.run --strategy nifty-expiry   # drive a named strategy
```

You'll watch the loop discover a variant that **beats a deliberately-mediocre baseline** and
surface it as `promote?` — held for a human gate (nothing promotes autonomously).

## One contract, two engines — the lab drives the locked IP

The real products — `nifty-weekday`, `nifty-expiry`, `sensex-expiry` — appear here **by name only**,
as synthetic stand-ins behind a single MCP contract, `run_backtest(params, strategy) → metrics`.
The **same agent loop drives either engine**: the public synthetic one you just ran, or the private
production strategies served behind the identical contract. Only the innermost **entry/exit logic is
proprietary** — protected by the contract boundary, not obfuscation, so this repo stays fully readable
and reproducible. This isn't a substitute for the real system; it's its **orchestration layer**, with
the edge swapped for a stand-in. See [architecture/01-strategy-research.md](architecture/01-strategy-research.md).

## What it demonstrates (the architecture)

```mermaid
flowchart LR
  S[Supervisor<br/>bounded loop] -->|propose| P[Proposer<br/>memory-guided]
  P -->|variants| B[Backtester<br/>via MCP tool]
  B -->|results| E[Evaluator<br/>risk-adjusted + LLM-judge]
  E -->|rank| S
  E -->|best| M[(Memory<br/>episodic/semantic)]
  M -.exploit.-> P
  E -->|promote?| H{{Human gate}}
```

- **Supervisor–worker** orchestration, **bounded autonomy** (iteration/token budget)
- **Memory-guided** proposals (exploit best-so-far + explore)
- **Offline↔online parity** — every variant judged on the *same* synthetic market
- **HITL** — the top variant is `promote?`, never auto-promoted

## Repository structure (monorepo — see [ADR-0004](docs/adr/0004-monorepo-and-environment-promotion.md))

```
research_lab/          # ★ Tier-1 · the agentic engine (supervisor + agents + memory)   [runnable]
synthetic_engine/      # ★ Tier-1 · public toy backtest engine (zero IP)                [runnable]
mcp_server/            #   Tier-1 · MCP tools over the engine
tests/  eval/          #   tests + the CI eval-gate (agent-loop regression)
chatbot/               #   Tier-1/2 · RAG + dual IP/PII guardrails + RBAC
slm_regime_classifier/ #   Tier-2 · fine-tuning use case (distill→QLoRA→serve→eval-gate)
ingestion/             #   Tier-3 · multimodal document ingestion (knowledge base)
api/  frontend/        #   Tier-3 · FastAPI gateway + React retail portal
knowledge_base/        #   corpus seed-list + eval sets (raw/processed are gitignored)
infra/                 #   IaC · environments/{dev,prod}  (dev/prod = envs, not branches)
ops/                   #   observability (OTel→LangSmith/Logfire/Langfuse), scripts
docs/                  #   architecture + ADRs
.github/workflows/     #   path-filtered CI/CD: lint · test · eval-gate → dev → prod
```

## Build tiers
- **Tier 1 (this)** — autonomous research loop + MCP + eval-gate + basic guarded chatbot. *Interview-credible.*
- **Tier 2** — model routing + the fine-tuning SLM.
- **Tier 3** — A2A + AWS deploy + retail portal + full multimodal ingestion.

## Architecture
Full system design across all subsystems — strategy research, ingestion, memory, guardrails,
frontend, observability, model routing, deployment: the [architecture/](architecture/) docs and
the decision records in [docs/adr/](docs/adr/). The ongoing decision journal — context and
trade-offs as the project evolves — is in [docs/DESIGN_LOG.md](docs/DESIGN_LOG.md).

## License
MIT.
</content>

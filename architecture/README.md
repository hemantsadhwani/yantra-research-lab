# Architecture

Production-grade design for **yantra-research-lab** — an autonomous multi-agent platform for
quant strategy research, plus the knowledge, guardrail, and delivery layers around it. Each
document below states the *decision, the why, and the cost/latency/scale/reliability trade-off*
(the ADR lens). The public build runs on a **synthetic engine** (zero proprietary IP); the
production version drives a private strategy engine, referenced here only in the abstract.

## The system in two diagrams

**The autonomous research loop**
```mermaid
flowchart LR
  subgraph LOOP[Supervisor · bounded by budget]
    P[Proposer<br/>memory-guided] --> B[Backtester<br/>MCP tool]
    B --> E[Evaluator<br/>risk-adjusted + LLM-judge]
    E --> R{rank} -->|iterate| P
  end
  E --> M[(Memory)]
  M -.exploit.-> P
  B --> ENG[[synthetic_engine · deterministic]]
  E --> H{{Human gate · promote?}}
```

**The product (monorepo tiers)**
```mermaid
flowchart TB
  subgraph T1[Tier 1 · core]
    RL[research loop] --- MCP[MCP tools] --- EV[eval-gate] --- CB[guarded chatbot]
  end
  subgraph T2[Tier 2 · differentiators]
    RT[model routing] --- SLM[fine-tuned SLM] --- OBS[observability]
  end
  subgraph T3[Tier 3 · platform]
    ING[multimodal ingestion] --- API[api · auth/RBAC] --- FE[retail portal] --- INF[infra dev/prod]
  end
  T1 --> T2 --> T3
```

## Index
| # | Document | Subsystem |
|---|---|---|
| 01 | [strategy-research](01-strategy-research.md) | the agentic research loop |
| 02 | [data-ingestion](02-data-ingestion.md) | multimodal near-zero-error pipeline |
| 03 | [memory](03-memory.md) | episodic / semantic / procedural agent memory |
| 04 | [guardrails-rbac](04-guardrails-rbac.md) | IP + PII guardrails, RBAC, leak-rate eval |
| 05 | [frontend-product](05-frontend-product.md) | product taxonomy, UI, plan-vs-actual |
| 06 | [observability](06-observability.md) | OTel → LangSmith/Logfire/Langfuse, evals + drift |
| 07 | [model-routing-finetune](07-model-routing-finetune.md) | LLM gateway + SLM distillation |
| 08 | [deployment-aws](08-deployment-aws.md) | AWS, monorepo, dev→prod promotion |

Decision records: [../docs/adr/](../docs/adr/).

## Design principles
1. **Workflow-first, agentic only where the problem demands it** — bounded autonomy; pay for it knowingly.
2. **Keep the LLM off the hot path** — deterministic control where latency matters.
3. **Deterministic fallbacks** around every probabilistic component.
4. **Eval-gate everything** — offline↔online parity; never ship a regression.
5. **Cost/compliance by routing** — cheap-local first, escalate to frontier models only where needed.
</content>

# Architecture

## The autonomous research loop (Tier-1, runnable)

```mermaid
flowchart LR
  subgraph LOOP[Supervisor · bounded by budget]
    P[Proposer<br/>memory-guided] --> B[Backtester<br/>MCP tool]
    B --> E[Evaluator<br/>risk-adjusted + judge]
    E --> R{rank}
    R -->|iterate| P
  end
  E --> M[(Memory<br/>episodic→semantic)]
  M -.exploit.-> P
  B --> ENG[[synthetic_engine<br/>zero IP · deterministic]]
  E --> H{{Human gate · promote?}}
```

## The product (monorepo tiers)

```mermaid
flowchart TB
  subgraph T1[Tier 1 · interview-credible]
    RL[research_lab] --- SE[synthetic_engine] --- MCP[mcp_server] --- EV[eval-gate]
    CB1[chatbot · basic guarded]
  end
  subgraph T2[Tier 2 · differentiators]
    SLM[slm_regime_classifier<br/>distill→QLoRA→serve] --- RT[model routing] --- OBS[observability]
  end
  subgraph T3[Tier 3 · showcase]
    ING[ingestion<br/>multimodal · event-driven] --- API[api · auth/RBAC] --- FE[frontend · retail portal] --- INF[infra · dev/prod]
  end
  T1 --> T2 --> T3
```

## CI/CD (path-filtered, environment promotion)

```
PR/merge → [changed?] → lint · test · eval-gate → deploy DEV → (manual approval) → PROD
```
Dev/prod are **environments**, not branches. See [adr/0004](adr/0004-monorepo-and-environment-promotion.md).

## ADRs
- [0001](adr/0001-public-synthetic-engine.md) public synthetic engine · [0002](adr/0002-mcp-wrap-the-engine.md) MCP-wrap ·
  [0003](adr/0003-bounded-autonomy.md) bounded autonomy · [0004](adr/0004-monorepo-and-environment-promotion.md) monorepo + env promotion.
</content>

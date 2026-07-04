# 06 · Observability & debug

Observability answers *"why did the agent do that, and is it degrading?"* — instrumented once on a
vendor-neutral **OpenTelemetry** backbone, then fanned out to the right surface per layer.

| Layer | Tool | Why this one |
|---|---|---|
| **Agent trajectories** (tool calls, hops, tokens, replay) | **LangSmith** | LangGraph-native; best agent-debugging DX — the primary lens |
| **Service traces + structured logs** (FastAPI/Pydantic) | **Logfire** | Pydantic-native, OTel-based; fits the stack |
| **Self-host / on-prem / no-egress** | **Langfuse** | OSS, self-hostable → the compliance/lock-in answer |
| **Quality (offline + online)** | LLM-as-judge + regression set + red-team leak-rate (**Inspect AI**) | evals *are* observability of correctness |
| **Cost / FinOps** | gateway cost callbacks + token meter | budget per run; catch a runaway loop |
| **Degradation** | embedding / response **drift** monitor | RAG and fine-tuned models rot silently |
| **Infra** | **CloudWatch** | latency / error / resource metrics for deployed services |

## The framing that matters
The three classic pillars — **traces · metrics · logs** — **plus two agentic pillars: evals · drift.**
Naming those two extra pillars is the difference between "we log stuff" and an observability
*strategy*.

## Decisions (ADR lens)
OTel backbone (vendor-neutral) → managed tools (LangSmith/Logfire) for DX, self-hostable (Langfuse)
when data can't leave the building — the same cost/compliance routing logic as model selection.
</content>

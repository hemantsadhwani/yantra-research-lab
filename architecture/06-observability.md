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

## As built (2026-09-13)
Only one row of the table above is actually wired: **Logfire**, via OpenTelemetry, on the FastAPI
backend.
| What | Detail |
|---|---|
| Spans | `chat_request → retrieve → llm`, per-request, for every `/api/chat` call |
| Metrics captured | latency split across those three spans, a token-cost estimate per call |
| Exposed as | `/api/metrics` on the backend — reads Logfire's aggregates back out (safe aggregates only, no per-user content) |
| Consumed by | the frontend's `/ops` "Live Ops" page, live on every page load |

**LangSmith, Langfuse, and CloudWatch are documented targets — none are wired.** There is no
agent-trajectory tracing (Tier-1's loop makes no LLM calls to trace), no self-hosted Langfuse
instance, and no CloudWatch integration (the backend runs on Fly.io, not AWS). The "evals as
observability" row is real in spirit but lives as standalone scripts (`eval/redteam.py`,
`eval/chatbot_books_eval.py`, `eval/run_gate.py` — see [04](04-guardrails-rbac.md) and
[README](README.md)), not wired into a drift-monitoring pipeline.
</content>

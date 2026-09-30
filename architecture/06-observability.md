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

## As built (2026-09-30)
Two rows of the table above are wired, both on **Logfire** over OpenTelemetry: the chatbot
service, and (new this week) the research loop's graph arm. Everything else is a target.

**Chatbot (`backend/observability.py`)**
| What | Detail |
|---|---|
| Spans | `chat_request → retrieve → llm`, per request, for every `/api/chat` call; provider and model are span attributes |
| Metrics captured | latency split across those spans, a token-cost estimate per call, `output_filtered` when the output guardrail withholds an answer |
| Exposed as | `/api/metrics`: Logfire aggregates (safe aggregates only, no per-user content) plus in-process `since_boot` counters (`attacks_blocked`, `output_filtered`) |
| Consumed by | the frontend's `/ops` "Live Ops" page, live on every page load |

The provider/model attributes, `output_filtered` and `since_boot` are in code (WP4, WP8) but not
yet deployed: on 2026-09-30 the live `/api/metrics` still returns the older shape (with the
hard-coded `leaks` field). Two cautions when reading it. (1) Local runs with `LOGFIRE_TOKEN` in
`.env` (backend `pytest`, `python -m eval.redteam --live`) send spans to the same project, tagged
`production` by default, and are counted as queries: on 2026-09-30 the endpoint read 100 queries with a 1 ms p50, and
its recent events were a local `eval.redteam --live` run. (2) So the all-time numbers are not user
traffic.

**Research loop (`research_lab/observability.py`, graph arm only)**
| What | Detail |
|---|---|
| Spans | one `research_run` (or `research_resume`) span per CLI invocation, and one `node.<name>` span per graph node: `baseline`, `propose`, `backtest_all`, `record`, `judge`, `gate`, `finalize` |
| Attributes | iteration, engine, provider, model, LLM calls and failures, input/output tokens, estimated cost, spend so far, stop reason, budget-exhausted iteration, judge calls / vetoes / abstentions. An `interrupt()` at the gate closes its span with `interrupted=true`, not as an error |
| Privacy | rationales and parameter values are never span attributes unless `YANTRA_TRACE_PARAMS=1` |
| Off by default | without `LOGFIRE_TOKEN` every helper is a no-op: no network, no console noise. The stdlib arm never imports it (`tests/test_smoke.py`) |

**Budget as the FinOps control.** The "Cost / FinOps" row is partly real: `research_lab/budget.py`
enforces a USD and call ceiling per run on both arms (`--max-usd`, `--max-llm-calls`), and every
run prints a footer such as `budget: $0.0000/$0.0500 · llm calls 0/∞ · stopped: iterations`.
Costs are list-price estimates from `llm_gateway/pricing.py`, not invoices.

**Not wired:** LangSmith, Langfuse and CloudWatch are documented targets with no integration.
The research-loop spans are tested against a stubbed `logfire` module
(`research_lab/tests/test_budget.py`); no Logfire dashboard is built on them, and nothing runs the
loop in a deployed environment that would emit them. There is no drift monitor. "Evals as
observability" is real but lives as scripts and CI gates (`eval/run_gate.py --arm both`,
`eval/redteam.py`, `eval/judge_eval.py`, `eval/chatbot_books_eval.py`; see
[04](04-guardrails-rbac.md) and [ADR-0010](../docs/adr/0010-evaluation-ladder.md)), not a
monitoring pipeline.

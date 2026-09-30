# Roadmap

What is in the tree today, and what is designed but deliberately not built yet. Every "Built" row
names the file that implements it and one command that proves it. The "Phase 2" rows are design
only. They used to be empty placeholder directories (`chatbot/`, `api/`, `infra/`, `ops/`,
`slm_regime_classifier/`); those were removed so the tree only holds code that runs. Their design
notes are collected here and in [architecture/](architecture/).

## Built

| Capability | Where | Proof |
|---|---|---|
| Stdlib research loop: propose, backtest, evaluate, rank, remember, iterate. Zero dependencies | `research_lab/supervisor.py`, `research_lab/run.py` | `python -m research_lab.run` |
| LangGraph arm: the same loop as a `StateGraph`, with a SQLite checkpoint and a real human interrupt before promotion | `research_lab/graph.py`, `research_lab/run_graph.py` | `python -m research_lab.run_graph`, then `python -m research_lab.run_graph --resume <thread> --decision approve` |
| MCP server + client: backtests over MCP stdio, byte-identical to the in-process engine | `mcp_server/server.py`, `research_lab/mcp_client.py` | `python -m research_lab.run --engine mcp` / `pytest research_lab/tests/test_mcp.py` |
| Provider gateway: Anthropic / Bedrock / Ollama behind one interface, schema-validated output | `llm_gateway/` | `LLM_PROVIDER=ollama python -m research_lab.run --use-llm` / `pytest llm_gateway/tests` |
| Context-engineering study: three context constructions measured against each other | `research_lab/experiments/context_study.py`, [`results/`](results/README.md) | `python -m research_lab.experiments.context_study --include-heuristic` |
| Persistent 3-layer memory: episodic, semantic, procedural over one SQLite file; learned priors; promotions human-only (`CHECK` constraint) | `research_lab/memory_store.py`, `research_lab/embeddings.py` | `make demo-memory` (run 2 reads `priors from 1 prior run`) / `pytest research_lab/tests/test_memory_store.py` |
| LLM-as-judge, veto only: may downgrade `promote?` to `hold`, never re-score, re-rank, upgrade or promote; gate shows the best surviving candidate | `research_lab/agents/judge.py`, `eval/datasets/judge_golden.jsonl` | `python -m research_lab.run_graph --judge` / `pytest research_lab/tests/test_judge.py` / `make judge-eval` (needs a key) |
| Enforced budget: USD and LLM-call caps on both arms, checked before every call; per-node Logfire spans on the graph arm | `research_lab/budget.py`, `research_lab/observability.py` | `python -m research_lab.run --max-usd 0.02` / `pytest research_lab/tests/test_budget.py` |
| Chatbot output filter with a measured leak rate (0/32 on, 6/32 off, hand-written leaks) | `backend/guardrails.py` (`check_output`) | `python -m eval.redteam --live` |
| Ingestion human gate as a real `interrupt()` over a SQLite checkpoint | `ingestion/graph.py`, `ingestion/run.py` | `pytest ingestion/tests/test_gate.py` |
| CI tiers: `core` (no extras), `agents`, `backend`, `ingestion`, `eval-gate` on both arms, red-team; gated prod deploy | `.github/workflows/ci.yml`, `eval/run_gate.py` | `python -m eval.run_gate --arm both` |
| FAISS backend for the chatbot retriever behind the same `Retriever` interface (`VECTOR_BACKEND=faiss`; Qdrant stays the default and the prod store); same top-1 as Qdrant on a 6-doc test corpus | `backend/retriever.py` (`FaissRetriever`), `backend/tests/test_faiss_backend.py` | `make demo-faiss` / `pytest backend/tests/test_faiss_backend.py` |
| RAG chatbot with IP + PII guardrails, deployed on Fly.io | `backend/` | `pytest backend/tests` / https://yantra-chatbot.fly.dev/docs |
| Ingestion pipeline: LangGraph DAG (discover, fetch, parse, caption, enrich, quality, index) on a daily cron | `ingestion/`, `.github/workflows/ingest.yml` | `INGEST_CORPUS_SIZE=5 python -m ingestion.run` |
| Evals: agent-loop regression gate, guardrail red-team, book-aware chatbot eval | `eval/` | `python -m eval.run_gate --arm both` / `python -m eval.redteam` |
| RAGAS-style chatbot eval: faithfulness, answer relevancy, context precision, context recall over 12 golden questions, via the chatbot's retrieval + answer path. Local implementation of the RAGAS definitions (the `ragas` package does not import next to LangGraph 1.x on 3.13). Offline fake judge in CI proves the harness only; the Haiku 4.5 judge run is not done yet | `eval/ragas_eval.py`, `eval/datasets/ragas_golden.jsonl`, [`results/ragas_2026-09-30.md`](results/ragas_2026-09-30.md) | `make ragas-eval` / `pytest tests/test_ragas_metrics.py backend/tests/test_ragas_eval.py` |
| MLflow tracking of eval runs (`run_gate`, `judge_eval`, `ragas_eval`), opt-in via `MLFLOW_TRACKING_URI`; no-op and never imported otherwise. Runs only; model registry not used | `eval/mlflow_tracking.py`, [`results/mlflow_2026-09-30.md`](results/mlflow_2026-09-30.md) | `MLFLOW_TRACKING_URI=file:./.mlruns python -m eval.run_gate --arm both && make mlflow-ui` / `pytest tests/test_mlflow_tracking.py` |
| Logfire tracing on the chatbot service | `backend/observability.py` | the `/ops` page on the live app |
| Containers + Kubernetes for the app layer: backend and frontend images, Compose with a private Ollama profile, kustomize manifests (probes, limits, HPA, Ingress), local kind cluster, CI image builds and manifest render. Not production: Fly + Vercel remain the deploy | `backend/Dockerfile`, `frontend/Dockerfile`, `docker-compose.yml`, `deploy/` | `make k8s-up && make k8s-smoke` / CI job `containers` |
| Next.js frontend on Vercel (Landing, Strategy Explorer, Research Lab, Chat, Ops, Pipeline) | `frontend/` | https://yantra-research-lab.vercel.app |

## Phase 2: designed, not built

| Capability | Design notes | Design doc |
|---|---|---|
| Auth + RBAC (Clerk or Cognito) | v1 is fully public on purpose. v2 adds sign-in, per-tenant isolation (one user never sees another's data) and role-scoped retrieval for the chatbot | [ADR-0006](docs/adr/0006-auth-rbac.md), [architecture/04](architecture/04-guardrails-rbac.md) |
| Retail portal + API gateway | FastAPI service for registration, simulated-capital allocation, multi-tenant portfolio state and research-run triggers. Paper / simulated only, no real money | [architecture/05](architecture/05-frontend-product.md), [ADR-0006](docs/adr/0006-auth-rbac.md) |
| A2A agent card | Expose the research loop as an agent that other agents can discover and call | not yet written |
| Model routing by task difficulty | Send cheap tasks to a small model and hard ones to a frontier model. Today there is one task and one model, so there is nothing to route yet | [architecture/07](architecture/07-model-routing-finetune.md) |
| SLM regime classifier: distill, QLoRA, serve, eval-gate | A frontier model labels a historical corpus into an SFT set (distill). A 4-bit Qwen SLM is QLoRA fine-tuned on it (finetune) and served via vLLM/Ollama at under 50 ms (serve). CI blocks a model that drifts outside tolerance of its teacher (eval-gate). The point is knowing where fine-tuning pays: the *intraday* gate needs cheap, low-latency, no-egress inference; the *daily* gate stays on the frontier API because fine-tuning would not amortize. Fine-tune to distill for cost, latency and compliance, not to add knowledge | [architecture/07](architecture/07-model-routing-finetune.md) |
| Walk-forward validation | Out-of-sample windows for every promoted variant, so a variant has to hold up on data it was not tuned on | not yet written |
| Postgres checkpointer | Swap the LangGraph SQLite checkpointer for Postgres so paused threads survive across hosts | not yet written |
| LiteLLM proxy | A central proxy in front of `llm_gateway/` for keys, spend tracking and fallbacks across services | [architecture/07](architecture/07-model-routing-finetune.md) |
| LangGraph chatbot with tools + SSE streaming | Move `backend/` from a single retrieval-then-answer call to a tool-using graph that streams tokens over SSE. | [architecture/04](architecture/04-guardrails-rbac.md) |
| Fargate + IaC environments | CDK or Terraform for ECS Fargate (agents + API), S3 + CloudFront, Cognito, CloudWatch. `dev` and `prod` are environments, not branches: CI promotes the same artifact from dev to prod and only env config differs. The CI `deploy-prod` job (Fly.io, environment-gated, enabled by the `ENABLE_FLY_DEPLOY` repo variable) is the interim deploy path | [ADR-0004](docs/adr/0004-monorepo-and-environment-promotion.md), [architecture/08](architecture/08-deployment-aws.md) |
| Observability beyond Logfire | Tracing on an OpenTelemetry backbone that fans out to LangSmith (agent trajectories), Langfuse (self-hosted, for compliance), a FinOps cost meter and a drift monitor | [architecture/06](architecture/06-observability.md) |

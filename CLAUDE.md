# yantra-research-lab

Autonomous multi-agent platform for quant strategy research. Agents propose strategy
variants → backtest each → judge on risk-adjusted returns → rank → remember what worked →
iterate for a fixed iteration count, with a human-approval gate before anything promotes.

This repo is a **public, reproducible showcase** of the orchestration layer of a private
trading system. It is also the flagship project on Hemant's resume and gets discussed in
interviews, so **accuracy matters more than polish** — see "Claims discipline" below.

## Commands

```bash
make install        # pip install -e '.[dev]'  — needed before pytest works
make demo           # stdlib arm: one research session (5 iterations x 6 variants)
make demo-graph     # LangGraph arm: same session, pauses at the human gate; then `make resume THREAD=... DECISION=approve`
                    # killed mid-run? `python -m research_lab.run_graph --resume <thread>` continues from the last checkpoint
make demo-mcp       # LangGraph arm over the MCP server (--engine mcp)
make demo-memory    # two graph runs over one SQLite memory; run 2 reads "priors from 1 prior run"
make demo-budget    # LLM graph run capped at $0.02; stops with "stopped: budget" (needs .[llm] + ANTHROPIC_API_KEY)
make judge-eval     # LLM judge vs 12 golden cases, pass >= 9/12 (needs a provider key; not in CI)
make demo-llm       # stdlib arm with the LLM proposer          (needs .[llm] + a provider: LLM_PROVIDER=)
make demo-bedrock   # LLM proposer via Claude on AWS Bedrock    (needs AWS creds + model access)
make context-study  # measure 3 context constructions          (needs .[llm] + API key, costs cents)
make test           # pytest
make gate           # eval-gate, stdlib arm (CI runs `python -m eval.run_gate --arm both`)
make lint           # ruff check .
make demo-faiss     # chatbot retrieval with VECTOR_BACKEND=faiss (exact cosine, on-disk index; Qdrant stays the default)
make ragas-eval     # RAGAS-style chatbot eval (faithfulness, relevancy, context precision/recall); --fake in CI, --provider anthropic for real
make layout-eval    # layout router: rules vs slm vs frontier, one table (--fake; rules row real, model rows scripted)
make distill-layout # CPU LoRA on SmolLM2-135M to emit layout labels (needs .[slm]; 25-min cap; not in CI)
make mlflow-ui      # browse eval runs logged when MLFLOW_TRACKING_URI is set (opt-in; file store under .mlruns/)
make docker-up      # backend + frontend with Compose (`--profile private` adds Ollama)
make k8s-up         # local kind cluster + ingress + both images + kustomize apply; then `make k8s-smoke`
```

Tier-1 core has **zero dependencies** — it runs on the stdlib, so `python -m research_lab.run`
works on a fresh clone. **Keep it that way.** The LLM proposer (`--use-llm`) is strictly opt-in:
the default path must never need an API key, a network call, or an installed SDK, because
"clone it and it reproduces" is a load-bearing property of this repo, not a convenience. Optional extras (`agents`, `llm`, `mcp`, `rag`, `ops`, `dev`, and `slm`, which is kept out of `all`) are
declared in `pyproject.toml` and installed per service.

(Windows only: prefix commands with `PYTHONIOENCODING=utf-8`; the report prints `→` and `⏸`.)

## The core design idea: one contract, two engines

The real strategies — `nifty-weekday`, `nifty-expiry`, `sensex-expiry` — appear here **by name
only**, as synthetic stand-ins behind a single MCP contract:

```
run_backtest(params, strategy) -> metrics
```

The *same* agent loop drives either engine: the public toy engine in `synthetic_engine/`, or
the private production strategies served behind the identical contract. Only the innermost
entry/exit logic is proprietary. **The IP is protected by the contract boundary, not by
obfuscation** — which is exactly why this repo stays fully readable and reproducible.

When changing anything near that boundary, preserve it: no real parameter values, no live
market data, no production entry/exit logic in this repo. See ADR-0001 and ADR-0002.

## Two proposers behind one method

`Proposer.propose(n, memory)` has two implementations: a deterministic memory-guided heuristic
(the default) and a structured Claude call (`use_llm=True`). Everything downstream — the
supervisor, the schemas, `verify.py`, the evaluator, the HITL gate — is identical either way.
That is deliberate and it is the ADR-0003 demonstration; **don't let the LLM path leak into the
loop.** If a change to the LLM proposer requires touching the supervisor, the seam has broken.

Two rules when working on it:
- **Never trust the model's output.** Proposals are clamped into `PARAM_SPACE` and still pass
  through `verify_variant`. Unusable output falls back to the heuristic *and increments
  `llm_failures`* — a degraded run must never look like a clean one.
- **Don't delete the deterministic path** to "simplify". It is the offline story and the control
  arm of the context study.

`research_lab/experiments/context_study.py` measures three context constructions against the
same loop. Its results live in `results/` — read `results/README.md` for what the numbers do and
do not support before quoting them anywhere.

## Layout

```
research_lab/          supervisor.py (stdlib loop, the spec) · graph.py + run_graph.py (LangGraph arm:
                       SQLite checkpoint, human interrupt, resume) · memory.py (in-process) ·
                       memory_store.py (SQLite: episodic / semantic / procedural) · embeddings.py ·
                       budget.py (USD / call cap, both arms) · observability.py (Logfire spans, graph arm) ·
                       mcp_client.py · schemas.py (dataclasses) · schemas_llm.py (Pydantic, LLM I/O only) ·
                       verify.py · run.py
research_lab/agents/   proposer.py, backtester.py (Backtester + MCPBacktester), evaluator.py,
                       judge.py (veto-only LLM judge), context.py
llm_gateway/           one provider interface: Anthropic direct · Claude on Bedrock · Ollama (LLM_PROVIDER=)
synthetic_engine/      engine.py — public toy backtest engine (zero IP)
mcp_server/            server.py — MCP tools wrapping the engine (run_backtest, get_param_space, ...)
eval/                  run_gate.py (--arm stdlib|graph|both), redteam.py (--live), judge_eval.py, chatbot_books_eval.py,
                       layout_eval.py (--fake)
backend/               FastAPI RAG chatbot + guardrails + Logfire (Fly.io)
ingestion/             LangGraph document-ingestion DAG (daily GitHub Actions cron) · layout_router.py (page
                       layout: rules | slm | frontier, YANTRA_LAYOUT_BACKEND, default rules, advisory) ·
                       layout_labels.py (page features + free teacher labels)
slm_regime_classifier/ distill_layout.py: CPU LoRA kata on the layout labels (regime classifier itself not built)
frontend/              Next.js portal (Vercel); frontend/Dockerfile for Compose / Kubernetes
deploy/                k8s/ kustomize manifests (probes, limits, HPA, Ingress) · kind/ local cluster (ADR-0011)
docs/                  architecture.md, DESIGN_LOG.md, adr/
architecture/          design docs 01–08 with honest "As built" sections
ROADMAP.md             Built (with the proving command) vs Phase 2 / designed-not-built
```

**Import boundary (enforced by `tests/test_smoke.py`, and by the CI `core` job, which installs no
extras):** optional SDKs are imported only in `graph.py` + `run_graph.py` (langgraph),
`mcp_client.py` (mcp, lazily), `schemas_llm.py` (pydantic), `embeddings.py` (fastembed, lazily on
first embed), `observability.py` (logfire, lazily; graph arm only) and `llm_gateway/*` (pydantic,
anthropic). `agents/proposer.py`, `agents/judge.py` and `run.py` reach `llm_gateway` / `schemas_llm`
only inside the LLM call or behind `--use-llm` / `--judge`. `run.py`, `supervisor.py`, `memory.py`,
`memory_store.py`, `budget.py`, `schemas.py`, `verify.py` and the heuristic proposer path import
none of langgraph / mcp / pydantic / anthropic / fastembed / logfire / opentelemetry at load time.

**Two arms, both eval-gated.** The stdlib supervisor and the LangGraph graph are individually deterministic
but produce different variant sequences for the same seed (the graph reseeds per iteration so a resumed run
reproduces). When quoting a number, say which arm produced it.

## Where the reasoning lives

Read these before re-deriving a decision — they record the trade-offs as they were made:

- `docs/DESIGN_LOG.md` — ongoing decision journal.
- `docs/adr/0001` public synthetic engine, private strategy stays verbal
- `docs/adr/0002` wrap the engine as MCP tools, not direct calls only
- `docs/adr/0003` bounded autonomy: workflow-shaped loop with agentic steps + HITL
- `docs/adr/0004` one monorepo for all tiers; dev/prod are environments, not repos
- `docs/adr/0005` public demo on a minimal-cost serverless stack; AWS is the business target
- `docs/adr/0006` auth & RBAC: none in v1; Clerk in v2
- `docs/adr/0007` LangGraph StateGraph is the primary arm; the stdlib supervisor stays the spec
- `docs/adr/0008` one `Provider` protocol (Anthropic / Bedrock / Ollama); thin adapter, not LiteLLM
- `docs/adr/0009` persistent memory over one SQLite file; promotions human-only
- `docs/adr/0010` evaluation ladder: verify → score → judge (veto only) → human; budget; leak rate
- `docs/adr/0011` app layer packaged for Kubernetes (Compose, kustomize, kind, CI image builds); Fly + Vercel stay the public demo
- `docs/adr/0012` SLM cascade: code → SLM → frontier; SLMs decide and score, frontier writes; swap in at ≥ 95% agreement

## Deployment

| Piece | URL |
|---|---|
| Frontend (Next.js → Vercel) | https://yantra-research-lab.vercel.app |
| Live Ops dashboard | https://yantra-research-lab.vercel.app/ops |
| Backend API docs (FastAPI → Fly.io) | https://yantra-chatbot.fly.dev/docs |

Frontend routes: `/`, `/strategies`, `/research-lab`, `/chat`, `/ops`, `/pipeline`.

Two gotchas:
- The Fly app is **`yantra-chatbot`** (see `backend/fly.toml`), *not* `yantra-backend`.
- The backend's **root path `/` returns 404** — there is no route there. Link `/docs`,
  `/health`, or `/api/metrics` instead.

`backend/fly.toml` now sets `min_machines_running = 1` and `auto_stop_machines = false` so
demo traffic never pays the ~20s cold start. That costs ~$2/mo; revert both to go back to
scale-to-zero. **Config changes require a deploy to take effect. Deploy from the repo root (the Docker context is the root since WP4): `fly deploy --config backend/fly.toml --dockerfile backend/Dockerfile .`**

**The chatbot's vector index lives in Qdrant Cloud, not in the image.** `QDRANT_URL` and
`QDRANT_API_KEY` are Fly secrets. The Dockerfile no longer builds a local index (removed in WP4;
prod never read it). After any corpus change, re-ingest against the cluster:

```bash
fly ssh console -a yantra-chatbot -C "sh -c 'cd /app && python ingest.py'"
```

A `fly deploy` alone does **not** update what the bot retrieves. This cost a full debugging cycle:
four deploys in a row appeared to change nothing, and stale `knowledge_base/README` chunks kept
coming back as top sources long after that file was excluded from ingestion.

`.github/workflows/ingest.yml` runs a daily 02:17 UTC cron on an ephemeral runner. It is
incremental against content-hashed S3 bronze, so most days re-process nothing, and it
auto-commits the refreshed manifest with `[skip ci]`.

## Claims discipline

This project is presented to recruiters and interviewers, so keep every public claim
verifiable against what the live endpoints actually return.

As of 2026-08-17, `/api/metrics` reported `queries_served: 1` all-time, p50 = p95 ≈ 20s (a
single cold-start sample), total cost $0.0038. It is genuinely deployed, traced and
observable — but it has **no real user traffic**.

So: call it a **"live app," never a "live product."** "Product" implies adoption, and the
`/ops` page an interviewer clicks is the very dashboard that shows one lifetime query. The
defensible claim is "deployed, reproducible, observable" — don't inflate past that, in the
README, the resume, or generated copy.

**Quote the arm and the test that proves it.** Any number or capability claim names which arm
produced it (stdlib supervisor or LangGraph graph; they explore different variant sequences for
the same seed) and the test or command that reproduces it, e.g. "graph arm, seed 3, best 36.5 vs
baseline 4.9: `python -m eval.run_gate --arm graph`". Anything not in code is written as "not built".

**Local runs can pollute the live metrics.** With `LOGFIRE_TOKEN` in `.env`, backend `pytest` and
`python -m eval.redteam --live` send spans to the production Logfire project, and `/api/metrics`
counts them as queries (on 2026-09-30 it read 100 queries at a 1 ms p50, mostly a local eval run).
Unset the token for local evals, and don't quote the all-time count as traffic.

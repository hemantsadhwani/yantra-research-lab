# yantra-research-lab

Autonomous multi-agent platform for quant strategy research. Agents propose strategy
variants → backtest each → judge on risk-adjusted returns → rank → remember what worked →
iterate, bounded by a budget, with a human-approval gate before anything promotes.

This repo is a **public, reproducible showcase** of the orchestration layer of a private
trading system. It is also the flagship project on Hemant's resume and gets discussed in
interviews, so **accuracy matters more than polish** — see "Claims discipline" below.

## Commands

```bash
make install     # pip install -e '.[dev]'  — needed before pytest works
make demo        # one autonomous research session (5 iterations x 6 variants)
make test        # pytest
make gate        # CI eval-gate: the agent loop must still beat the baseline
make lint        # ruff check .
```

Tier-1 core has **zero dependencies** — it runs on the stdlib, so `python -m research_lab.run`
works on a fresh clone. Optional extras (`agents`, `llm`, `mcp`, `rag`, `ops`, `dev`) are
declared in `pyproject.toml` and installed per service.

**On Windows, prefix commands with `PYTHONIOENCODING=utf-8`.** The report writer emits `→`
and `⏸`, and the default `cp1252` console encoding raises `UnicodeEncodeError` at the end of
an otherwise successful run. The loop itself is fine — only the final print dies.

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

## Layout

```
research_lab/          supervisor.py, memory.py, schemas.py, run.py
research_lab/agents/   proposer.py, backtester.py, evaluator.py
synthetic_engine/      engine.py — public toy backtest engine (zero IP)
mcp_server/            server.py — MCP tools wrapping the engine
eval/                  run_gate.py — the CI eval-gate
chatbot/               RAG + dual IP/PII guardrails + RBAC
slm_regime_classifier/ Tier-2: distill -> QLoRA -> serve -> eval-gate
ingestion/             Tier-3: multimodal document ingestion
api/ frontend/         FastAPI gateway + Next.js portal
infra/ ops/            IaC (dev/prod are environments, not branches) + observability
docs/                  architecture.md, DESIGN_LOG.md, adr/, runbooks/
```

## Where the reasoning lives

Read these before re-deriving a decision — they record the trade-offs as they were made:

- `docs/DESIGN_LOG.md` — ongoing decision journal.
- `docs/adr/0001` public synthetic engine, private strategy stays verbal
- `docs/adr/0002` wrap the engine as MCP tools, not direct calls only
- `docs/adr/0003` bounded autonomy: workflow-shaped loop with agentic steps + HITL
- `docs/adr/0004` one monorepo for all tiers; dev/prod are environments, not repos
- `docs/adr/0005` public demo on a minimal-cost serverless stack; AWS is the business target
- `docs/adr/0006` auth & RBAC: none in v1; Clerk in v2

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
scale-to-zero. **Config changes require `fly deploy` from `backend/` to take effect.**

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

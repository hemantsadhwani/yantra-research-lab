# Fable one-shot build prompt — yantra-research-lab, public web app (v1)

> **How to use:** open this repo in a Fable session and paste the prompt below (everything under
> "PROMPT"). It builds the v1 public site + chatbot on top of the existing Python agent loop.
> It needs **no API keys to build** — all secrets are read from `.env` at runtime.

---

## PROMPT

You are building **v1 of the public web app** for `yantra-research-lab`, an autonomous multi-agent
quant strategy-research platform. The Python core already exists in this repo; you are adding the
web frontend, the RAG chatbot backend, and deploy configs. Work at high effort; give the full build
in one pass, then verify it runs.

### 0. Read first (the locked decisions — do not re-litigate)
- `README.md`, `docs/DESIGN_LOG.md`, `docs/adr/0001`…`0006`, and `architecture/01,04,05,08`.
- Existing code you will reuse, **not rewrite**: `research_lab/` (supervisor→proposer→backtester→
  evaluator loop), `synthetic_engine/` (deterministic backtest engine, multi-strategy registry),
  `mcp_server/` (the `run_backtest` MCP contract), `eval/` (CI gate).

### 1. NON-NEGOTIABLE constraints (privacy, cost, scope)
1. **Never expose strategy logic.** The real entry/exit rules are proprietary and are NOT in this
   repo. Do not invent, infer, or request them.
2. **Never put real trading P&L numbers in code.** The Strategy Explorer performance panel MUST read
   from `frontend/public/data/performance.json`, which you create with **clearly-fake placeholder
   values** (e.g. `0.0`) and a `"_note": "PLACEHOLDER — owner fills real numbers from private
   master"`. Do not ask for real numbers.
3. **Mandatory labels** on any performance display: *"Simulation / educational · backtest not
   live-executed · % summed, not compounded · no performance promises."*
4. **No auth in v1** — the whole app is public. Do not add login/Clerk/Cognito.
5. **Cost discipline:** the Research Lab screen is **cached** (reads a committed `run.json`) — it
   must make **zero LLM calls per visitor**. The chatbot uses **Claude Haiku** with prompt caching,
   a **per-IP rate limit**, and a **daily request cap**.
6. **Secrets from env only** — never hardcode; update `.env.example`; never commit `.env`.
7. **Don't break** the existing eval-gate or the zero-dependency Tier-1 loop.

### 2. Frontend — Next.js (App Router, TypeScript) in `frontend/`, deploy on Vercel
**Visual reference:** `docs/wireframe.html` is a static mockup of the intended "Signal Desk"
aesthetic and the screen layouts — open it in a browser and match the *look and structure* (dark
oscilloscope/phosphor terminal feel, tickers, cards, tables, the chat launcher). **All numbers in
it are fake placeholders** — do not treat any figure there as real data.

Tasteful, professional, responsive, light+dark. Four screens + a persistent "Ask" chat launcher:

1. **Landing** — hero explaining the autonomous loop (propose → backtest → judge → rank → remember,
   bounded by budget, human-approval gate). Prominent **paper-only / simulation** disclaimer.
2. **Strategy Explorer** — the three named strategies (`nifty-weekday`, `nifty-expiry`,
   `sensex-expiry`) as cards, plus a **Plan-vs-Actual / capture-factor panel** reading
   `performance.json` (placeholders) with the mandatory labels. Explain capture-factor = live ÷
   backtest as an honesty feature.
3. **Research Lab** — render the cached `run.json`: the supervisor→workers pipeline, the iteration/
   budget, the ranked variants table (rank, variant, return, win, drawdown, score, verdict), and the
   **HITL "promote?" gate**. Static render, no backend call.
4. **Chatbot page** — full chat UI calling `POST {BACKEND_URL}/api/chat`. Show the **dual guardrail**
   framing (refuses strategy IP, protects PII) and a visible **leak-rate: 0** badge. Invite the user
   to try to jailbreak it.

Config: `NEXT_PUBLIC_BACKEND_URL` from env. Keep it a static/SSR site that deploys clean on Vercel.

### 3. Backend — FastAPI in `backend/`, containerized, deploy on Fly.io (scale-to-zero)
- **`Retriever` interface** with `QdrantRetriever` behind it: Qdrant **local on-disk mode** (no
  server) by default; set `QDRANT_URL` (+`QDRANT_API_KEY`) for Qdrant Cloud. Keep the interface so
  an `OpenSearchRetriever` can slot in for multi-tenant scale (the "one contract, swappable engines"
  seam) — but do NOT add a FAISS backend.
- **Embeddings:** local, via **fastembed** (`BAAI/bge-small-en-v1.5`, ONNX — lightweight, no torch,
  good for scale-to-zero). No API key.
- **Ingestion script** `backend/ingest.py`: load the corpus from `knowledge_base/` (methodology docs
  + quant-paper notes; if sparse, include a small seed set of general-quant markdown) → chunk →
  embed → index. **Basic RAG only** — not the Tier-3 multimodal pipeline.
- **`POST /api/chat`:** retrieve top-k → build a prompt → call **Claude Haiku** (`claude-haiku-4-5`)
  via the Anthropic SDK (`ANTHROPIC_API_KEY` from env) with **prompt caching**. Stream if easy.
  - **Guardrails:** (a) IP — strategy parameters/edge are kept OUT of the index (defense in depth) +
    a refusal policy that declines requests for strategy params/logic; (b) PII — redact PII in
    prompts/logs; (c) basic prompt-injection detection. Return a `leak_rate`-style signal the UI can
    show.
  - **Cost controls:** per-IP rate limit (e.g. 20 req/min) + a global daily request cap; both env-
    configurable; return HTTP 429 when exceeded.
- **CORS** allow the Vercel origin (env `FRONTEND_ORIGIN`).
- Health check `GET /health`.

### 4. Generate the cached research run
Add `scripts/generate_run.py` that runs `research_lab.supervisor.Supervisor` (the existing
deterministic, no-API-key loop) and writes `frontend/public/data/run.json` in a shape the Research
Lab screen consumes. Commit a generated `run.json` so the site renders without any backend.

### 5. Deploy configs & docs
- `frontend/`: standard Next.js — Vercel auto-detects. Add any needed `vercel.json`.
- `backend/`: `Dockerfile` (slim Python 3.11) + `fly.toml` (scale-to-zero, min machines 0).
- Update root `.env.example` with every new var (`ANTHROPIC_API_KEY`, `NEXT_PUBLIC_BACKEND_URL`,
  `FRONTEND_ORIGIN`, `VECTOR_BACKEND`, rate-limit/cap vars).
- Add a `WEBAPP.md` (or extend `README.md`) with **run-locally** and **deploy** steps for both
  frontend and backend.

### 6. Acceptance criteria (verify these before finishing)
- `cd frontend && npm install && npm run dev` serves all four screens; Research Lab shows the cached
  ranked variants from `run.json`.
- `cd backend && pip install -e . && python ingest.py && uvicorn app:app` runs; `POST /api/chat`
  returns an answer grounded in the corpus, and **refuses** a "what are the exact strategy
  parameters?" question.
- The rate limit returns 429 past the threshold.
- No secret is hardcoded; `.env.example` lists everything; `.env` stays git-ignored.
- The existing `python -m eval.run_gate` still passes.

### 7. Do NOT do
- No auth/login (v1). No real P&L numbers or strategy logic. No multimodal/agentic ingestion
  (Tier-3). No live per-visitor research runs (cached only). No AWS services (Vercel + Fly for v1).
  Don't modify `synthetic_engine/`, `research_lab/`, or `eval/` behavior — only consume them.

Build it, run the acceptance checks, and summarize what you created and any follow-ups.

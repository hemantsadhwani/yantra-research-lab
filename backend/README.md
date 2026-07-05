# backend/ — Public RAG chatbot (FastAPI + Claude Haiku)

A small, runnable retrieval-augmented chatbot for the research lab, with **dual
IP/PII guardrails**. It answers questions about general quant *methodology* only —
it will not reveal proprietary strategy parameters or entry/exit logic, and it
redacts user PII.

## What's here

| File | Purpose |
|---|---|
| `app.py` | FastAPI app: `/health`, `/api/chat`; CORS, rate limiting, daily cap. |
| `guardrails.py` | `redact_pii`, `detect_injection`, `should_refuse`, and the LLM system prompt. |
| `retriever.py` | Abstract `Retriever` + `QdrantRetriever` (local on-disk; set `QDRANT_URL` for Qdrant Cloud). Interface kept so OpenSearch can slot in for multi-tenant scale. |
| `embeddings.py` | Local embeddings via `fastembed` (`BAAI/bge-small-en-v1.5`, ONNX — no torch, no API key). |
| `ingest.py` | Load markdown → chunk (~500 tokens, overlapping) → embed → index. |
| `seed_corpus/` | 8 built-in methodology notes (mean reversion, z-scores/Bollinger, backtesting parity, Sharpe, drawdown, options Greeks, walk-forward, capture factor). |
| `tests/test_guardrails.py` | Guardrail unit tests (no API key needed). |
| `Dockerfile`, `fly.toml` | Container + Fly.io scale-to-zero deploy. |

## The chat API contract

`POST /api/chat`

Request:
```json
{
  "message": "what is mean reversion?",
  "history": [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]
}
```

Response:
```json
{
  "answer": "…",
  "refused": false,
  "sources": [{"title": "Mean Reversion", "snippet": "…"}],
  "leak_rate": 0
}
```

`GET /health` → `{"status": "ok"}`

Guardrail behaviour: prompt-injection attempts and requests for proprietary strategy
parameters / entry-exit rules / "the edge" return `refused: true` with a polite
refusal **without calling the LLM**. Per-IP rate limiting (429) and a global daily cap
(429) protect against abuse/cost.

## Run locally

```bash
cd backend

# 1. Install deps (choose one)
pip install -r requirements.txt
# or: pip install -e .

# 2. Build the local vector index.
#    First run downloads the fastembed ONNX model (~130 MB) — needs network once.
python ingest.py

# 3. Serve. ANTHROPIC_API_KEY is read from the repo-root .env automatically
#    (python-dotenv + find_dotenv), or from the environment.
uvicorn app:app --reload --port 8000
```

Smoke test:
```bash
curl localhost:8000/health
curl -s localhost:8000/api/chat -H 'content-type: application/json' \
  -d '{"message":"what is mean reversion?","history":[]}' | python -m json.tool
```

## Configuration (env vars)

| Var | Default | Meaning |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Required to generate answers (read from `.env` in dev; platform-set in prod). |
| `FRONTEND_ORIGIN` | `http://localhost:3000` | Allowed CORS origin. |
| `QDRANT_URL` | — | Unset = Qdrant local on-disk mode. Set (+ `QDRANT_API_KEY`) = Qdrant Cloud/container. |
| `CHAT_MODEL` | `claude-haiku-4-5` | Anthropic model id. |
| `TOP_K` | `4` | Retrieved chunks per query. |
| `RATE_LIMIT_PER_MIN` | `20` | Per-IP requests/minute. |
| `DAILY_REQUEST_CAP` | `500` | Global requests/day. |

## Tests

```bash
cd backend
pip install pytest
pytest            # runs tests/test_guardrails.py — no API key required
```

## Deploy (Fly.io, scale-to-zero)

`fly.toml` sets `min_machines_running = 0` with `auto_stop_machines` / `auto_start_machines`,
so machines sleep when idle and wake on the next request. The `Dockerfile` runs
`python ingest.py` at build time so the image ships with the index prebuilt.

```bash
cd backend
fly launch --no-deploy            # first time: create the app from fly.toml
fly secrets set ANTHROPIC_API_KEY=sk-ant-...
fly secrets set FRONTEND_ORIGIN=https://your-frontend.example.com
fly deploy
```

If your build environment blocks the model download, drop the `RUN python ingest.py`
line from the `Dockerfile` and run `python ingest.py` in your machine start command
instead (with a persistent volume for the index).

## Guardrail note (defense in depth)

The index holds **general methodology only** — it must never contain proprietary
strategy parameters, thresholds, or entry/exit logic. `ingest.py` documents this, and
`should_refuse` in `app.py` is a second, independent line of defence at request time.

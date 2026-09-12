# Running & deploying the v1 web app

The public demo = a **Next.js frontend** (`frontend/`) + a **FastAPI RAG chatbot** (`backend/`),
on top of the existing Python research loop. Accounts/keys: see [SETUP.md](SETUP.md). No auth in v1.

```
frontend/   Next.js — Landing · Strategy Explorer · Research Lab · Chatbot   → Vercel
backend/    FastAPI — RAG chatbot, Qdrant retriever, IP/PII guardrails → Fly.io (scale-to-zero)
scripts/    generate_run.py — regenerates the cached Research-Lab run.json
```

## Prerequisites
- `ANTHROPIC_API_KEY` in `.env` (see SETUP.md — set a spend cap).
- Node.js 20+, Python 3.11+.

## Run locally

**1. Backend** (terminal 1):
```bash
cd backend
python3.12 -m venv .venv && source .venv/bin/activate   # Python 3.12 (see .python-version)
pip install -r requirements.txt          # or: pip install -e .
python ingest.py                          # builds the local vector index (first run downloads a small embedding model)
uvicorn app:app --reload --port 8000
```
> **Python 3.12** is pinned (`.python-version`) — safest for `fastembed`/`onnxruntime`/`qdrant`.
> 3.13 wheels for those can be flaky. The `.venv/` is git-ignored (never committed).

**2. Frontend** (terminal 2):
```bash
cd frontend
npm install
npm run dev                               # http://localhost:3000
```

Open http://localhost:3000. The Research Lab screen renders the cached run; the Chatbot talks to the
backend on :8000. Try to make the chatbot reveal strategy parameters — it should refuse (leak-rate 0).

## Refresh the cached Research-Lab run
```bash
python scripts/generate_run.py frontend/public/data/run.json
```
Deterministic (no LLM calls) — commit the regenerated `run.json`.

## Fill the real performance numbers (separate, manual step)
`frontend/public/data/performance.json` ships with **placeholders**. Replace them with the real,
**labeled** figures from your private master when you're ready — keep the mandatory labels
(*simulation / educational · backtest not live-executed · % summed, not compounded · no promises*).
Do this by hand so real numbers never pass through a build tool.

## Strategy books (real numbers)
`frontend/public/data/books/*.json` holds real, labeled backtest **outputs** for the private
strategies (`nifty-weekday`, `nifty-expiry`, `sensex-expiry`) behind the Strategy Explorer —
see `frontend/src/lib/types.ts` for the `Book`/`BooksIndex`/`RiskGatesData` shapes. The
`headline`/`cost`/`sizing` figures are transcribed by hand from the private monthly reports;
`monthly`/`daily` stay `[]` with `series_pending: true` until filled in. Fill them by running
`scripts/export_books.py` **in the private repo** against the real trades CSV, then commit
only the resulting JSON here — the CSV itself never enters this repo. Outputs only, always:
no engine parameters, indicator names or thresholds, entry/exit logic, exit-type names, or
trade-level rows ever get published, in these files or anywhere else on the public site.

## Deploy
**Backend → Fly.io** (from `backend/`):
```bash
fly launch          # accept the fly.toml; one machine stays warm
fly secrets set ANTHROPIC_API_KEY=sk-ant-...   # set the key as a Fly secret (not in the image)
fly secrets set FRONTEND_ORIGIN=https://<your-vercel-domain>
fly deploy
```
Note the backend URL — this deployment is `https://yantra-chatbot.fly.dev`
(matches `app = "yantra-chatbot"` in `backend/fly.toml`).

**Frontend → Vercel**:
1. Import the GitHub repo in Vercel; set **Root Directory = `frontend`**.
2. Env var `NEXT_PUBLIC_BACKEND_URL = https://<your-backend>.fly.dev`.
3. Deploy — you get a `*.vercel.app` URL (add a custom domain later).

Then set the backend's `FRONTEND_ORIGIN` to the Vercel URL so CORS allows it.

## Cost
Research Lab is cached → $0/visitor. Chatbot is Haiku + caching + rate-limit + daily cap. Backend
keeps one warm machine (`min_machines_running = 1`) so demo traffic never hits a ~20s cold start —
that trades scale-to-zero for ~$2/month of always-on `shared-cpu-1x`. Estimate: **~$3–7/month + domain.**
See [docs/adr/0005-public-demo-deployment.md](docs/adr/0005-public-demo-deployment.md).

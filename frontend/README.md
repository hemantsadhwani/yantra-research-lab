# frontend/ — yantra-research-lab public web (v1)

The **"Signal Desk"** public frontend: a dark AI+quant terminal look (with a light theme) for the
autonomous strategy-research showcase. Built with **Next.js (App Router) + TypeScript + Tailwind CSS**.

> **ALL PAPER / SIMULATED — educational, not investment advice.** Strategy numbers are labeled
> backtest outputs (simulated fills, not live-executed); the research-lab run is from the public
> synthetic engine. No real funds are held, moved, or managed.

## Screens

| Route            | What it is                                                                              |
| ---------------- | --------------------------------------------------------------------------------------- |
| `/`              | Landing — explains the loop: propose → backtest → judge → rank → remember (budgeted, HITL gate). |
| `/strategies`    | Strategy Explorer — 3 products / 7 books of labeled backtest outputs (`public/data/books/`) + Plan-vs-Actual **capture-factor** panel (`public/data/performance.json`). |
| `/research-lab`  | Research Lab — the agentic pipeline, budget, baseline + ranked-variants table, and the `promote?` gate. Reads `public/data/run.json`. **Zero backend calls.** |
| `/chat`          | Guardrail chatbot — POSTs to the backend, shows sources, refusals, and a live **leak-rate** badge. |

A floating **"▚ Ask"** launcher opens a compact chat popover on every page (except `/chat`, which is
the full chat). It reuses the same backend endpoint and chat logic.

## Data files

Static JSON in `public/data/` (server-rendered at build time):

- `books/*.json` — real, labeled backtest outputs for the strategy books, including the monthly
  P&L series (published 2026-09-12). Outputs only: no parameters, entry/exit logic or trade rows.
- `run.json` — one cached deterministic run of the public synthetic engine
  (regenerate with `python scripts/generate_run.py frontend/public/data/run.json`).
- `performance.json` — feeds only the Plan-vs-Actual panel; its values are still placeholders
  until live paper results are filled in.
- `ingestion.json` — the ingestion pipeline manifest behind `/pipeline`.

## Run locally

```bash
cd frontend
npm install
cp .env.local.example .env.local   # optional — defaults to http://localhost:8000
npm run dev                         # http://localhost:3000
```

Production build:

```bash
npm run build
npm run start
```

## Configuration

| Env var                   | Default                 | Purpose                                          |
| ------------------------- | ----------------------- | ------------------------------------------------ |
| `NEXT_PUBLIC_BACKEND_URL` | `http://localhost:8000` | Base URL of the chatbot backend. The chat UI POSTs to `${NEXT_PUBLIC_BACKEND_URL}/api/chat`. |

### Chat API contract

`POST ${NEXT_PUBLIC_BACKEND_URL}/api/chat`

```jsonc
// request
{ "message": "…", "history": [{ "role": "user", "content": "…" }] }
// response
{ "answer": "…", "refused": false, "sources": [{ "title": "…", "snippet": "…" }], "leak_rate": 0 }
```

## Deploy on Vercel

1. Import this repository into Vercel.
2. Set **Root Directory** to `frontend/`.
3. Framework preset: **Next.js** (auto-detected). Build command `npm run build`.
4. Add the env var **`NEXT_PUBLIC_BACKEND_URL`** pointing at your deployed backend.
5. Deploy.

## Theming

Dark-first. Respects `prefers-color-scheme` and offers a toggle (persisted to `localStorage`, applied
before paint to avoid a flash). Fully responsive with no horizontal body scroll.

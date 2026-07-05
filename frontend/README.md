# frontend/ — yantra-research-lab public web (v1)

The **"Signal Desk"** public frontend: a dark AI+quant terminal look (with a light theme) for the
autonomous strategy-research showcase. Built with **Next.js (App Router) + TypeScript + Tailwind CSS**.

> **ALL PAPER / SIMULATED — educational, not investment advice.** Every number in this app is a
> placeholder or a simulated result. No real funds are held, moved, or managed.

## Screens

| Route            | What it is                                                                              |
| ---------------- | --------------------------------------------------------------------------------------- |
| `/`              | Landing — explains the loop: propose → backtest → judge → rank → remember (budgeted, HITL gate). |
| `/strategies`    | Strategy Explorer — 3 paper strategy cards + Plan-vs-Actual **capture-factor** panel. Reads `public/data/performance.json`. |
| `/research-lab`  | Research Lab — the agentic pipeline, budget, baseline + ranked-variants table, and the `promote?` gate. Reads `public/data/run.json`. **Zero backend calls.** |
| `/chat`          | Guardrail chatbot — POSTs to the backend, shows sources, refusals, and a live **leak-rate** badge. |

A floating **"▚ Ask"** launcher opens a compact chat popover on every page (except `/chat`, which is
the full chat). It reuses the same backend endpoint and chat logic.

## Data files

Static JSON in `public/data/` (server-rendered at build time; the owner overwrites these with real
cached data):

- `run.json` — one cached research run (baseline + ranked variants). Placeholder stub included.
- `performance.json` — strategy + plan-vs-actual numbers. **Placeholder zeros — fill with real labeled numbers.**

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

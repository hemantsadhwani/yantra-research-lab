# 05 · Frontend & product

The delivery surface: an investor/participant portal over the research platform. **All
performance shown is paper/simulated** — labelled simulation/education, no performance promises,
no real capital (real-money management is a separately-regulated activity).

## Product taxonomy — a first-class dimension
`Product = (asset class → strategy family)`, modelled now, built incrementally:

| Product (nav) | Status |
|---|---|
| **Options** | live strategies |
| **Futures** | roadmap |
| **Swing — Equities** | roadmap |

Modelling *product* as a first-class dimension (not a single hard-coded strategy) is the
extensibility decision — the schema and UI accommodate new asset classes without a rewrite.

## Screens
1. **Landing** — guest entry (no signup), hero = the agent loop, paper-only disclaimer above the fold.
2. **Strategy explorer** — product switcher + strategy cards (paper performance), every card stamped PAPER.
3. **Research lab** — the agentic loop made visible: supervisor→workers, budget, ranked variants, HITL gate.
4. **Portfolio** — allocate *simulated* capital across strategies; personal (tenant-isolated) dashboard; agent post-mortems.
5. **Chatbot** — the IP/PII-guardrail assistant (see [04](04-guardrails-rbac.md)) on every screen.

## Plan-vs-Actual — parity as a product feature
A panel that shows, per period, **backtest-expected vs live-realized** performance and the
**capture factor `f = live ÷ backtest`**. Surfacing the honest gap between simulation and reality
*builds trust* — it's the offline↔online parity discipline turned into a UI. (Illustrative shape;
figures shown in a deployment come from that deployment's own data.)

## Architecture
- **Static SPA (React/Next) on S3 + CloudFront** — cheap, scalable, cacheable; server-rendered only where needed.
- **Cognito** for registration + **RBAC** (guest / member / owner) — the same roles that scope the chatbot.
- **Multi-tenant isolation** — each participant's simulated portfolio is their own; never cross-tenant.
- Theme-aware, accessible; the design language is a "signal-desk" quant-terminal aesthetic.

## Decisions (ADR lens)
Static S3+CloudFront vs server-rendered (cost/scale) · Cognito for auth+RBAC · product as a
first-class taxonomy (extensibility) · paper-only labelling (regulated-domain judgment) ·
plan-vs-actual as an honesty feature.

## As built (2026-09-13)

**Screens — the six real routes** (Next.js 14.2.5 / React 18, deployed on Vercel):

| Route | What's actually there |
|---|---|
| `/` | Landing |
| `/strategies` | **Strategy Explorer** — 3 product tabs (NIFTY weekday, NIFTY expiry, SENSEX expiry) + a Risk gates tab; real labelled backtest *outputs* from `frontend/public/data/books/*.json`, cumulative + monthly charts |
| `/research-lab` | the agent loop, replayed from a cached deterministic run (not live) |
| `/chat` | the guardrailed chatbot (see [04](04-guardrails-rbac.md)) |
| `/ops` | Live Ops — real Logfire aggregates via the backend's `/api/metrics` (see [06](06-observability.md)) |
| `/pipeline` | the ingestion DAG/lineage/dead-letter view (see [02a](02a-data-ingestion-asbuilt.md)) |

- **No Portfolio screen exists** — it's roadmap, not built. The **Plan-vs-Actual** panel described
  above exists in the UI but currently renders placeholder zeros (no live-vs-backtest data feed yet).
- **Architecture, as built:** static Next.js app on Vercel, auto-deployed on push to `main`; **no
  auth** ([ADR-0006](../docs/adr/0006-auth-rbac.md) — v1 ships with none); data comes from static
  JSON checked into `frontend/public/data/` (books, ingestion manifest), not a live database.
- **Target, not built:** the Portfolio screen, Cognito auth/RBAC, S3+CloudFront hosting (Vercel is
  the actual host), multi-tenant isolation. Clerk is the documented v2 auth path, per ADR-0006.

### Strategy books — how outputs reach the site
The data path behind `/strategies` and the chatbot's book answers: private monthly-report PDFs →
`scripts/extract_monthly_from_reports.py` (reconciles bar geometry to printed totals) +
hand-transcribed headline stats → `frontend/public/data/books/*.json` → consumed by the site
directly, and by the chatbot corpus via `scripts/sync_books_corpus.py`. Everything in this path is
**published outputs only** (P&L, drawdown, win rate, sizing, risk-gate thresholds) — never engine
parameters or entry/exit logic. `scripts/export_books.py` is the documented future path straight
from the trades CSV, replacing the current hand-transcription step.
</content>

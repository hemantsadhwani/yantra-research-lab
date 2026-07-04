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
</content>

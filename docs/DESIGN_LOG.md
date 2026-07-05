# Design Log

A running record of design decisions and their rationale — the *why behind the what*,
newest entries first. Complements the two other design surfaces:

- **[docs/adr/](adr/)** — formal, frozen architecture *decisions* (one per file).
- **[architecture/](../architecture/)** — subsystem *designs* (the system as it stands).
- **This log** — the ongoing decision *journal*: context, trade-offs, and notes captured as
  the project evolves, before they harden into an ADR.

---

## 2026-07-05 — Public demo: deployment, IP boundary, cost model

### One contract, two engines — named strategies behind MCP
The three products (`nifty-weekday`, `nifty-expiry`, `sensex-expiry`) appear in this repo
**by name only**, as synthetic stand-ins behind the single `run_backtest(params, strategy)`
MCP contract. The **same agent loop drives either engine** — the public synthetic engine here,
or the real production strategies served privately behind the identical contract. IP is
protected by the **contract boundary, not obfuscation** (no compiled blobs), so the repo stays
readable and `clone && run`. See [architecture/01-strategy-research.md](../architecture/01-strategy-research.md)
and [ADR-0002](adr/0002-mcp-wrap-the-engine.md). *Status: implemented, tested, eval-gate green.*

### IP boundary — publish the architecture, protect only the edge
Design principle: **everything is public except the strategy entry/exit logic** (the edge).
Architecture, methodology, the synthetic engine, and *honest* live-vs-backtest reporting are
all in the open; only the rules that constitute the trading edge stay private, server-side,
behind the MCP contract. The Strategy Explorer's **Plan-vs-Actual / capture-factor panel**
reports the live-vs-backtest gap honestly — always labeled *simulation / educational · backtest
not live-executed · % summed, not compounded · no performance promises.* Surfacing that gap is
treated as a **credibility feature**, not something to hide. See [ADR-0001](adr/0001-public-synthetic-engine.md).

### Public deployment — minimal-cost, scale-to-zero (AWS is the scale target)
The demo deploys cheaply now; the AWS design in
[architecture/08-deployment-aws.md](../architecture/08-deployment-aws.md) is the documented
scale target, not built yet. Full rationale in [ADR-0005](adr/0005-public-demo-deployment.md):

| Layer | Demo (now) | Scale target |
|---|---|---|
| Frontend | Next.js on **Vercel** (free CDN) | S3 + CloudFront |
| API + chatbot | FastAPI in **one scale-to-zero container** (Cloud Run / Fly) | ECS Fargate |
| Vector | **Qdrant** (local → cloud via `QDRANT_URL`), behind a `Retriever` interface | Qdrant Cloud / OpenSearch |
| LLM | **Claude Haiku** + prompt caching | model routing |

Site v1 = 4 screens (Landing · Strategy Explorer · Research Lab · live guarded Chatbot); no auth
in v1. Same "one contract, two engines" swap-the-implementation pattern as the backtest engine —
the RAG code never changes when the vector store does.

### Cost / FinOps model — cheap on purpose, bounded by design
Cost control is treated as an architecture decision, not an afterthought:

- **The research lab on the site is pre-computed / cached → $0 per visitor.** LLM tokens are spent
  only when the loop is run **offline** to regenerate the committed showcase run.
- **One full research-lab run ≈ $0.10–1.50** depending on model tier; **backtests are free**
  (local synthetic engine, no LLM).
- **Chatbot ≈ pennies per query** (Haiku pricing) + prompt caching + a **hard daily spend cap +
  per-IP rate limit** (also the abuse guardrail — the chatbot invites jailbreak attempts).
- **Bounded by design:** the token + iteration budget and the human-in-the-loop promote gate mean
  the agent loop *cannot* run away; **model routing** escalates to a stronger model only where the
  reasoning is hard. Bounded autonomy is a FinOps control, not just a safety one.
- Estimated running cost: **~$1–5 / month + domain.**

### Auth & RBAC — none in v1, Clerk in v2
v1 ships with **no authentication** — the whole MVP is public (guests browse + use the chatbot).
When the retail portal lands (v2), authentication + RBAC use **Clerk** — Google login as the
low-friction default, with roles + organizations built in — at **~$0** on the free tier. RBAC roles:
**guest / member / admin**, plus **tenant isolation** that feeds the chatbot's PII guardrail. **AWS
Cognito** stays the documented AWS-scale target (same deploy-cheap-document-AWS pattern). Login
method and RBAC are separate concerns: Google is *how you log in*; roles are *what you can do*. Full
rationale in [ADR-0006](adr/0006-auth-rbac.md).

### Build sequencing — Tier-1 MVP first
The completion bar for the interview-credible core (Tier-1) is: the autonomous
propose → backtest → judge → rank loop (done) + MCP + eval-gate + a **basic-RAG** guarded chatbot
+ a live public URL. The full **agentic multimodal ingestion pipeline is Tier-3** — built later,
not part of the MVP. Chatbot v1 uses basic RAG only (methodology docs + quant papers → chunk →
embed → Qdrant). Anti-scope-creep: ship the MVP, then extend. See the tiers in the
[README](../README.md).

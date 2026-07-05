# ADR-0005 — Public demo deploys on a minimal-cost serverless stack; AWS is the business target

**Status:** accepted · 2026-07-04

## Question
How do we put a **public, always-on URL** in front of the platform — a live site + working
chatbot an interviewer can open — at the **lowest possible cost** (self-funded, job-search
purpose now), without weakening the "industry-grade, scalable" architecture story or the path to
a real multi-tenant business product after the PMS licence?

## Decision
Deploy the **demo** on a **minimal-cost, scale-to-zero serverless stack**, and keep the
AWS design ([architecture/08-deployment-aws.md](../../architecture/08-deployment-aws.md)) as the
**documented business target** built post-licence. Deploy cheaply; *design and document* the
scaled version. Same philosophy as the Tier system and the synthetic-vs-real engine seam.

| Layer | Demo (now) | Business target (post-PMS) |
|---|---|---|
| **Frontend** | **Next.js on Vercel** — free global CDN, auto-HTTPS, custom domain | S3 + CloudFront |
| **API + chatbot** | **FastAPI in one scale-to-zero container** (Cloud Run / Fly.io) | ECS Fargate |
| **Vector store** | **Qdrant** (local on-disk mode), behind a `Retriever` interface | Qdrant Cloud / self-host, or OpenSearch |
| **LLM** | **Claude Haiku 4.5** + prompt caching | model routing (Haiku↔frontier) |
| **Auth** | **none** (fully public read + chatbot) | Cognito (registration + RBAC) |
| **Domain** | one `.com` (~$12/yr) | same |

**Estimated cost: ~$1–5 / month + $12 / year domain.**

## Why serverless-cheap, not a VM or full AWS now
- **Scale-to-zero = ~$0 when idle.** A portfolio site gets sporadic traffic; an always-on VM
  (EC2/Lightsail) bills 24/7 for nothing and adds patching/security ops we don't want to own yet.
- **Container = portable.** The same FastAPI image that runs on Cloud Run today lifts to Fargate
  later with no code change — the demo *is* a step toward the business target, not throwaway.
- **Stronger interview signal, honestly told:** *"Deployed scale-to-zero for a few dollars a month
  because it's a showcase; here's the AWS multi-tenant architecture it grows into."* FinOps
  discipline reads as senior, not cheap.

## Vector store — Qdrant behind a `Retriever` interface
Retrieval sits behind a `Retriever` contract (`index()` / `search()`):
- **`QdrantRetriever`** — the industry-standard vector database; **local/embedded on-disk mode now**
  (free, no server), upgrades to **Qdrant Cloud / a container** just by setting `QDRANT_URL` — zero
  code change. A future `OpenSearchRetriever` slots in behind the same contract for multi-tenant scale.
- FAISS was considered as an in-process fallback but dropped: Qdrant's local mode already gives the
  embedded, no-server benefit, so a second engine was redundant.

This is the same "one contract, two engines" seam as the backtest engine (ADR-0002): the RAG code
never changes when the store does. Consistent with the vector row in
[architecture/08-deployment-aws.md](../../architecture/08-deployment-aws.md) and the
`sqlite-vec → OpenSearch` progression in [architecture/03-memory.md](../../architecture/03-memory.md).

## Cost guardrails (non-negotiable — and a FinOps talking point)
1. **Scale-to-zero / free tiers only** — no idle compute billing.
2. **LLM spend cap + per-IP rate limit + prompt caching** — a hard daily token/$ ceiling so a
   viral moment *or a jailbreak-spammer* (the chatbot literally invites attack) cannot drain the wallet.
3. **Static frontend on a CDN free tier** — never pay to serve HTML.
4. **Embedded vector store** — no managed-DB monthly bill until multi-tenant.
5. **Billing alarm at ~$10** on the cloud account.

## Site v1 scope (MVP — 4 of the 5 wireframe screens)
- **Landing** — the agent-loop hero + paper-only/simulation disclaimer.
- **Strategy Explorer** — the three named strategies + the **Plan-vs-Actual / capture-factor panel**
  carrying the **real numbers**, each labeled *"simulation / educational · backtest not live-executed
  · % summed, not compounded · no performance promises"* (design §8 + SEBI/DPDP). This is the
  success-story surface; only the strategy *logic* stays private (ADR-0001).
- **Research Lab** — a **pre-computed / cached** ranked-variant run rendered from committed JSON
  (zero per-visitor LLM cost; the "live" feel comes from the chatbot).
- **Chatbot** — the live IP/PII-guardrail RAG bot over a **basic** ingestion (methodology docs +
  quant papers → chunk → embed → Qdrant). NOT the Tier-3 agentic multimodal pipeline.
- **Deferred:** the Member Dashboard + login/RBAC (Tier-3 retail portal, post-PMS).

## Consequences
- Add a deploy target under `infra/environments/{dev,prod}`: a Vercel project (frontend) + a
  container service (API/chatbot). CI stays path-filtered (ADR-0004); the eval-gate + a RAG-golden
  + red-team leak-rate check gate promotion.
- The chatbot needs a `Retriever` interface + a **basic ingestion script** before it can answer.
- Research Lab needs a committed `run.json` artifact (regenerated by the eval-gate run).
- **Readiness:** application-ready at **end of Tier-1 + live URL + basic chatbot** — do *not* gate
  applying on the agentic ingestion pipeline (Tier-3; built while interviewing, per design §4).

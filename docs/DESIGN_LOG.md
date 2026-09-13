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

### Strategy Explorer — real numbers, outputs only, no database (2026-09-12)
The Explorer now shows **real, labeled backtest outputs** for the three products — `nifty-weekday`
(HIGH-VIX · LOW-VIX · a PAPER continuation sub-book), `nifty-expiry` (HIGH-VIX · LOW-VIX) and
`sensex-expiry` — as **product tabs with a per-book sub-toggle**, plus a **Risk gates** tab
(daily / weekly / monthly stops and what they cannot save you from). Three decisions:
- **Outputs, not mechanism.** Headline tiles, monthly/daily P&L, drawdown, sizing base and
  LIVE/PAPER status are published; the engine panel (indicators, thresholds, bands, harvest
  rules), exit-type breakdowns and trade rows are not — they *are* the edge ADR-0001 protects.
  "Net over peak %" is also dropped: it reads as a compounded return and breaks claims discipline.
- **Static JSON, not a DB.** Seven books × 13 months, refreshed monthly, is a
  `frontend/public/data/books/*.json` problem, served free by Vercel through the existing
  `data.ts` loaders. A database would add a paid dependency and let real numbers flow through a
  build step, which WEBAPP.md forbids. Revisit only if the site should refresh itself from the bot.
- **The PDFs are not the source.** Only headline numbers are transcribable from the monthly
  reports (bars label peaks only, daily is a scatter). Series come from `scripts/export_books.py`,
  run **inside the private repo** against the trades CSV; only the aggregated JSON crosses over,
  after a sum-vs-headline consistency check. Until then each book carries `series_pending: true`
  and the UI draws an explicit placeholder — never a synthetic curve.

### Chatbot knows the books — hybrid routing, outputs only (2026-09-12)
A visitor asked the live bot for the SENSEX expiry P&L and it (correctly) had nothing: the
corpus was methodology-only and the Fly image copies just `backend/`. Now
`scripts/sync_books_corpus.py` renders the book JSONs into `backend/books_corpus/*.md` (with a
`--check` drift mode), `ingest.py` indexes them, and `backend/books.py` adds a **deterministic
keyword router**: name a product and its doc (plus the overview, plus risk gates on risk words)
is always in context — vector retrieval alone was a gamble with a small embedding model. The
system prompt gains four rules: quote the published outputs with their labels, never
extrapolate/annualise/convert to %, say "pending" when the monthly series is, and keep refusing
mechanism. Because book names are now in the corpus, naming a product counts as a "specific"
marker in `should_refuse` — "what threshold does the nifty weekday book use?" is refused,
"why did the sensex expiry book stop trading in Feb?" is not. Red-team eval: 100% block, 0 FP.

### Monthly series recovered from the report charts, reconciled not estimated (2026-09-12)
The books shipped with `series_pending: true` because the monthly reports print only the one-to-three
peak month labels; the rest are unlabeled bars. They are not unrecoverable, though: matplotlib emits
each bar as a 4-corner vector path, so `scripts/extract_monthly_from_reports.py` reads the signed bar
geometry (uniform width, shared zero line) and scales it by the single factor that makes the series
sum to the **printed** book total. That is a reconciliation, not an eyeball — and it is falsifiable:
all 16 printed month labels across the seven books reproduce to ±0.00, and each series independently
matches the book's `months_traded` and `months_up` (zero-P&L axis months are kept but excluded from
"traded", which is exactly how the reports count them). Each book records `monthly_source` saying it
is chart-derived and will be superseded by `export_books.py` run against the trades CSV. The PDFs
themselves are never ingested — they carry the engine panel, exit breakdowns and trade tables.

### The RAG was the weak part, not the ingestion (2026-09-12)
The bot answered "I don't have that" for figures sitting in its own corpus, then — worse — invented
a fluent, confident, wrong answer about overfitting when asked what the risk gates don't protect
against. Four defects, in rising order of nastiness:
1. **No conversation memory.** The router read only the current message, so "what is max draw down?"
   after three turns about SENSEX matched no product and fell through to the methodology index.
2. **Shared vocabulary routed one way only.** "drawdown" was a performance word, so textbook
   questions dragged book context in, while "max loss per day" matched nothing at all. A definition
   guard now splits both directions.
3. **An eval that graded the wrong answer.** Q16 asserted the second-deepest drawdown, so a reply
   naming the wrong book — and contradicting itself two lines later — passed. Substring assertions
   are not enough: the grader now fails self-correction phrases and requires a book doc in `sources`.
   The fix upstream was to state the rankings in the overview instead of making the model sort rows.
4. **The index was somewhere else entirely.** `QDRANT_URL` is a Fly secret, so the app reads Qdrant
   *Cloud* while `Dockerfile`'s `RUN python ingest.py` builds a local index nobody queries. Four
   deploys changed nothing about retrieval; the stale cluster still served `knowledge_base/README`
   chunks whose source file wasn't even in the image. Re-ingest over SSH is now documented in
   CLAUDE.md and warned about in the Dockerfile.
The lesson worth keeping: retrieval failures are invisible from the outside. The bot sounds equally
confident whether it retrieved the right document, the wrong one, or nothing at all — so the eval
has to assert on the retrieved sources, not just the prose.

### The chatbot now reads what the pipeline writes (2026-09-13)
The architecture diagrams made one thing embarrassing to look at: `research_corpus` — 376 chunks
from ten arXiv papers, re-indexed nightly by the Tier-3 pipeline — was never queried. The chatbot
searched `methodology` only, so a question about a paper the site says it ingested got an answer
from the model's memory, not the corpus. That is the RAG equivalent of a dashboard nobody reads.

The fix is read-side only. `QdrantRetriever.search()` now queries every collection in
`QDRANT_READ_COLLECTIONS` (default `methodology,research_corpus`), asks each for k so a strong
corpus cannot starve a weak one, merges by cosine score and cuts to k. That merge is honest only
because both pipelines embed with the same `bge-small-en-v1.5`; with different models the scores
would not be comparable and this would need a re-ranker. A missing collection logs a warning and
is skipped, so local dev without the pipeline still works, and the retrieve span records hits per
collection so Logfire shows whether papers were actually served. `index()` still writes only
`methodology` — the two corpora stay separate (blue/green data); they are simply both read.

Verified live before and after: "what is entropic value-at-risk parity?" cites the paper by title.
`eval/chatbot_books_eval.py` gained Q22–Q23, which fail unless an arXiv title appears in
`sources`, and a 3.2s inter-request pause so the eval itself stops tripping the 20/min limit.
This was a `fly deploy`, not a re-ingest: the retriever changed, the index did not.

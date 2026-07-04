# ingestion/ — multimodal, agentic, event-driven document pipeline  ·  Tier 3

Populates the chatbot's knowledge base from quant PDFs (text · tables · formulas · diagrams),
with near-zero error (verification loop + confidence-gated HITL) and event-driven incremental
updates (drop 2–3 docs → auto-ingest → vector DB current).

**Layout (see the full design):** `acquire/` (arXiv/S3 fetch) · `extract/` (layout→text/table/
formula/figure) · `verify/` (critic + HITL) · `index/` (chunk · contextual-embed · upsert) ·
`librarian.py` (dedup by hash · manifest · staging→eval-gate→promote).

Full architecture + ADRs + tool picks:
`../job_profile/ai_enginerring/MULTIMODAL_INGESTION_ARCHITECTURE.md`.
Seed corpus: `../knowledge_base/seed_papers.md`.
</content>

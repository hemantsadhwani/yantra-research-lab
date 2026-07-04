# 02 · Data ingestion — multimodal, agentic, near-zero-error

Populates the knowledge base from quant PDFs (text · tables · formulas · statistical diagrams)
with near-zero error and event-driven incremental updates. Reusable across any RAG product.

> **Honesty on "near-zero error":** no single OCR model is near-zero (SOTA ~90–95% on
> OmniDocBench). Near-zero is an *architecture* property — a verification/reflection loop +
> confidence-gated **human-in-the-loop** for the tail — not a magic model.

## Two paradigms — route by document quality
| Paradigm | What | Best for |
|---|---|---|
| **Parse-to-text** | OCR/VLM → structured markdown/JSON (tables→HTML, formulas→LaTeX) | born-digital PDFs — cheap, accurate |
| **OCR-free visual** | embed the *page image* (ColPali/ColQwen), late-interaction retrieval | scanned / diagram-heavy pages where OCR errors hurt |

Don't pick one — **route**: born-digital → text path, scanned/figure-heavy → visual path, index both.

## Scalable topology — 3-tier microservices + queues
```
                 ┌ ingest queue ┐   ┌ worker queue ┐   ┌ status queue ┐
 PDFs ─▶ GATEWAY ┘  (I/O)         └─▶ WORKERS ──────┘─▶ INFERENCE ─────┘─▶ INDEX
         object-store = truth       async orchestration  GPU · model-per-container
```
- **Object storage = source of truth; queues carry pointers** → any tier restarts/scales with zero data loss + backpressure.
- **Checkpoint per step** → resume from last good step; idempotent (visibility timeout > P99).
- **GPU inference decoupled** → scale the expensive tier alone; OCR is ~⅔ of latency, so that's the tier to batch/autoscale.
- **Cheap-local + API-escalation** → classify/extract locally, escalate the hard ~4% to a frontier VLM (~10× cost cut).

## Extraction pipeline (per doc)
```
layout+route → specialist extract (text · tables · formulas→LaTeX · figures→VLM caption)
            → VERIFY + self-correct (critic VLM · confidence · low-conf → 2nd model → HITL)
            → assemble + chunk (reading-order · provenance) → multi-rep index → retrieve
```

## Incremental, event-driven ingestion (steady state)
```
drop docs → s3://raw/incoming → EventBridge → SQS → LIBRARIAN (hash-dedup vs manifest)
   → pipeline → UPSERT to STAGING namespace → EVAL-GATE → PROMOTE to LIVE   (rollback = delete by doc_id)
```
- Event trigger (not polling) + nightly reconciliation safety net.
- **Idempotent dedup by content hash** — same doc twice never double-ingests.
- **Incremental UPSERT, never rebuild** — O(new), not O(all).
- **Staging → eval-gate → promote** — a bad doc can't pollute live knowledge.

## Retrieval at scale
Hybrid **dense + BM25 + visual (ColQwen)**; **pooled two-stage late interaction** (candidate via
pooled vectors → MaxSim rerank; ~4× QPS, vectors/page thousands→dozens); **contextual retrieval**
(prepend chunk-context → ~49% fewer failures, ~67% with a reranker); distributed vector DB (Qdrant/Weaviate).

## Robustness
Eval harness in CI (extraction accuracy per element + retrieval NDCG); verification loop +
confidence-gated HITL; **agentic only where it wins** (route hard/multi-hop to agentic retrieval,
simple to plain hybrid); embedding/response **drift** monitoring.

## Tool picks (2026, self-host-first)
Layout/text: **dots.ocr · Docling · MinerU** · Tables: **TableFormer/GOT-OCR2** · Formulas:
**Mathpix/GOT-OCR2** · Figures: **Qwen2.5-VL / Claude vision** · Visual retrieval: **ColQwen2.5/3** ·
Vector DB: **Qdrant/Weaviate** · Embeddings: **Voyage/BGE** · Eval: RAGAS + Inspect AI (CI-gated).

## Key ADRs
Parse-to-text **+** OCR-free, routed by quality · 3-tier microservices + queues · incremental
event-driven upsert + staging eval-gate · near-zero = verification + HITL · self-host + API
escalation · hybrid + contextual retrieval + pooled late interaction · agentic only where it wins.
</content>

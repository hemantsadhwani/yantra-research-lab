# Tier-3 — Agentic Multimodal Ingestion Pipeline

A near-zero-cost data pipeline that builds the research knowledge base: it discovers
open-access quant-finance papers, extracts their **text, tables, images and formulas**,
enriches and quality-gates each document with bounded LLM agents, and indexes the
survivors into a vector store — orchestrated as a **LangGraph StateGraph**.

Engineered as a real data platform, not a script. Deliberately **separate from the
serving API** (`backend/`) so the runtime container stays lean.

## Pipeline

```
discover ─▶ fetch ─▶ parse ─▶ caption ─▶ enrich ─▶ quality ─▶ [human gate] ─▶ index
 arXiv      S3       PyMuPDF   figures    chunk +    dedup ·      HITL          bge-small
 q-fin      bronze   text/     → vision   Haiku      relevance ·  approval      → Qdrant
 API        (hash)   tables/   caption    summary    IP-leak                    research_corpus
                     formulas  (Claude)   + topics   quarantine                 + lineage catalog
```

Each stage returns a partial state update; documents accumulate fields as they advance.
Modules: `discover.py` `fetch.py` `parse.py` `figures.py`+`caption.py` `enrich.py`
`quality.py` `index.py`, wired in `graph.py`, run by `run.py`. Data contracts in `state.py`;
pluggable storage in `storage.py`.

**Multimodal (sub-project A).** Figures are located by anchoring on their captions and
rasterizing the region defined by the figure's own vector/image geometry (this catches
arXiv's vector plots that `get_images()` misses). Each figure's full-res PNG goes to S3
bronze; a small thumbnail is committed for the public site; a bounded **Claude vision**
call captions it; the caption is embedded into `research_corpus` — so a text query
retrieves the matching figure (caption-based multimodal retrieval; the paper's printed
caption is the fallback when vision is off/over-budget).

## Data-engineering properties

| Property | How |
|---|---|
| **Medallion architecture** | bronze (raw PDFs, S3) → silver (parsed) → gold (indexed chunks) |
| **Idempotent + incremental** | content-hash keys; a daily re-run reprocesses only what changed |
| **Data contracts** | pydantic models at every stage boundary (`state.py`) |
| **Retries + checkpointing** | LangGraph `RetryPolicy`; fetch backoff |
| **Dead-letter / quarantine** | failures + rejects captured *with reasons*, never dropped silently |
| **Governance** | IP-leak quality gate enforces the privacy boundary for private sources |
| **Lineage** | per-doc provenance in the catalog + the public manifest |
| **Observability** | Logfire traces the run + every LLM call; per-run cost |
| **Cost control** | offline batch, Haiku-only enrichment, hard USD budget, cached artifact |
| **Blue/green data** | writes to `research_corpus`, separate from the live `methodology` index |
| **Storage abstraction** | pluggable Local ⇄ S3 (`storage.py`) via one env var |

## Run

```bash
pip install -r ingestion/requirements.txt          # separate from backend deps
python -m ingestion.run                            # full run
INGEST_CORPUS_SIZE=3 python -m ingestion.run       # small smoke run
```

Reads `.env` (repo root) for `ANTHROPIC_API_KEY`, `QDRANT_URL`/`QDRANT_API_KEY`,
optional `LOGFIRE_TOKEN`, and optional S3 (`S3_BUCKET`, `AWS_*`). Runs in CI daily via
`.github/workflows/ingest.yml`, which commits the refreshed manifest back to auto-redeploy
the site.

## Deliberately deferred (documented upgrades)

Knowing what *not* to build is part of the design. Each is a one-flag/one-module add:

- **Tables → Text-to-SQL** — structured tables → DuckDB → schema-linked LLM SQL agent
  with execution-feedback self-correction (automates reporting). Sub-project B.
- **High-fidelity math** — Nougat / Mathpix / arXiv LaTeX source (v1 flags `has_math`).
- **Heavy layout analysis** — `unstructured` hi-res / GROBID (v1 uses PyMuPDF geometry).
- **GraphRAG** — entity-relationship graph for multi-hop questions (v1 is vector RAG).
- **CLIP image-vectors** — visual-similarity search in a parallel space.

These are omitted from the near-zero core on purpose; the value/cost tradeoff doesn't
justify them until a demo needs them.

> Fuller design notes / ADRs (aspirational architecture): see
> [../architecture/02-data-ingestion.md](../architecture/02-data-ingestion.md) if present.

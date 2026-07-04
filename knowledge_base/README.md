# knowledge_base/ — corpus, seed-list, and eval sets

- **`seed_papers.md`** — the 50-paper quant reading-list for the initial backfill.
- **`eval_sets/`** *(committed)* — golden RAG QA + red-team leak/PII attack sets; the CI eval-gate
  runs against these so corpus/retrieval changes can't silently regress.
- **`raw/`, `processed/`** *(gitignored)* — dropped PDFs and extracted artifacts; populated at
  runtime by the `ingestion/` pipeline (event-driven: drop → ingest → staging → eval-gate → live).
</content>

"""CLI entry point for the Tier-3 ingestion pipeline.

    python -m ingestion.run                 # full run (discover→…→index)
    INGEST_CORPUS_SIZE=5 python -m ingestion.run   # small run for a smoke test

Runs the LangGraph pipeline, then writes a SAFE public manifest (frontend/public/data/
ingestion.json) that the site's /pipeline screen renders — counts, per-doc provenance,
rejects-by-reason, spend. No raw content leaves here. Logfire-traced end to end when
LOGFIRE_TOKEN is set.
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

# Make repo root importable when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingestion import config  # noqa: E402
from ingestion.graph import build_graph  # noqa: E402

DAG = [
    {"id": "discover", "label": "Discover", "desc": "arXiv q-fin API — source catalog"},
    {"id": "fetch", "label": "Fetch", "desc": "download PDFs → S3 bronze (content-hash, incremental)"},
    {"id": "parse", "label": "Parse", "desc": "PyMuPDF text+tables+images, formula flag, OCR fallback"},
    {"id": "enrich", "label": "Enrich", "desc": "chunk + LLM summary/topics (Haiku, budget-bounded)"},
    {"id": "quality", "label": "Quality gate", "desc": "dedup · relevance · IP-leak quarantine"},
    {"id": "gate", "label": "Human gate", "desc": "HITL approval before indexing"},
    {"id": "index", "label": "Index", "desc": "embed (bge-small) → Qdrant research_corpus + catalog"},
]


def _load_env() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(config.REPO_ROOT / ".env")
    except Exception:
        pass


def _configure_logfire():
    try:
        import logfire

        logfire.configure(service_name="yantra-ingestion", environment="batch",
                          send_to_logfire="if-token-present", console=False)
        logfire.instrument_anthropic()
        return logfire
    except Exception:
        return None


def main() -> None:
    _load_env()
    config.ensure_dirs()
    logfire = _configure_logfire()

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    t0 = time.monotonic()

    graph = build_graph()
    span = logfire.span("ingestion_run", run_id=run_id) if logfire else None
    if span:
        span.__enter__()
    try:
        final = graph.invoke(
            {"run_id": run_id, "rejects": [], "spent_usd": 0.0, "stats": {}},
            {"recursion_limit": 50},
        )
    finally:
        if span:
            span.__exit__(None, None, None)

    duration = round(time.monotonic() - t0, 1)
    parsed = final.get("parsed", [])
    rejects = final.get("rejects", [])
    accepted = final.get("accepted", [])
    reasons = Counter(r["reason"] for r in rejects)

    manifest = {
        "_note": ("Public run manifest of the Tier-3 agentic ingestion pipeline. "
                  "Safe aggregates + provenance only; raw PDFs live in S3, not here."),
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "collection": config.COLLECTION,
        "embed_model": config.EMBED_MODEL,
        "dag": DAG,
        "stats": {
            "discovered": len(final.get("sources", [])),
            "fetched": len(final.get("fetched", [])),
            "parsed": len(parsed),
            "chunks": len(final.get("chunks", [])),
            "accepted": len(accepted),
            "rejected": len(rejects),
            "images": sum(p.get("n_images", 0) for p in parsed),
            "tables": sum(p.get("n_tables", 0) for p in parsed),
            "with_math": sum(1 for p in parsed if p.get("has_math")),
            "indexed": final.get("indexed", 0),
            "spent_usd": round(final.get("spent_usd", 0.0), 4),
            "duration_s": duration,
        },
        "rejects_by_reason": dict(reasons),
        "budget_usd": config.TOKEN_BUDGET_USD,
        "docs": [
            {
                "id": p["source_id"],
                "title": p["title"],
                "source": p["pdf_url"],
                "pages": p.get("n_pages", 0),
                "images": p.get("n_images", 0),
                "tables": p.get("n_tables", 0),
                "has_math": p.get("has_math", False),
                "ocr_used": p.get("ocr_used", False),
                "chunks_indexed": sum(1 for c in accepted if c["doc_id"] == p["source_id"]),
            }
            for p in parsed
        ],
    }
    config.MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    s = manifest["stats"]
    print(f"run {run_id} · {duration}s")
    print(f"  discovered {s['discovered']} · parsed {s['parsed']} · "
          f"images {s['images']} · tables {s['tables']} · math-docs {s['with_math']}")
    print(f"  chunks {s['chunks']} → accepted {s['accepted']} (rejected {s['rejected']}: {dict(reasons)})")
    print(f"  indexed {s['indexed']} into '{config.COLLECTION}' · spent ${s['spent_usd']}")
    print(f"  manifest → {config.MANIFEST_PATH}")


if __name__ == "__main__":
    main()

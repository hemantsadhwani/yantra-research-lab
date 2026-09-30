"""CLI entry point for the Tier-3 ingestion pipeline.

    python -m ingestion.run                 # full run; pauses at the human gate
    python -m ingestion.run --thread my-run # name the run (default: a UTC timestamp)
    python -m ingestion.run --resume <thread> --approve   # index the pending docs
    python -m ingestion.run --resume <thread> --reject    # end the run, index nothing
    python -m ingestion.run --list          # checkpointed runs and where each stopped
    INGEST_AUTO_APPROVE=1 python -m ingestion.run   # no pause (what CI does)
    INGEST_CORPUS_SIZE=5 python -m ingestion.run    # small run for a smoke test

Runs the LangGraph pipeline (checkpointed to ingestion/data/state/checkpoints.sqlite), then writes a SAFE public manifest (frontend/public/data/
ingestion.json) that the site's /pipeline screen renders — counts, per-doc provenance,
rejects-by-reason, spend. No raw content leaves here. Logfire-traced end to end when
LOGFIRE_TOKEN is set.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

# Make repo root importable when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingestion import config
from ingestion.graph import build_graph, default_checkpointer

DAG = [
    {"id": "discover", "label": "Discover", "desc": "arXiv q-fin API — source catalog"},
    {"id": "fetch", "label": "Fetch", "desc": "download PDFs → S3 bronze (content-hash, incremental)"},
    {"id": "parse", "label": "Parse", "desc": "PyMuPDF text+tables+images, formula flag, OCR fallback"},
    {"id": "caption", "label": "Caption", "desc": "rasterize figures → Claude vision caption (multimodal)"},
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


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="python -m ingestion.run")
    ap.add_argument("--thread", help="run/thread id (default: a UTC timestamp)")
    ap.add_argument("--resume", metavar="THREAD", help="resume a run paused at the gate")
    decision = ap.add_mutually_exclusive_group()
    decision.add_argument("--approve", action="store_true")
    decision.add_argument("--reject", action="store_true")
    ap.add_argument("--list", action="store_true", help="list checkpointed runs")
    args = ap.parse_args(argv)
    if args.resume and not (args.approve or args.reject):
        ap.error("--resume needs --approve or --reject")
    if (args.approve or args.reject) and not args.resume:
        ap.error("--approve/--reject only make sense with --resume <thread>")
    return args


def list_threads(checkpointer) -> list[tuple[str, tuple]]:
    """``[(thread_id, next_nodes)]`` for every checkpointed run, newest first."""
    threads = {c.config["configurable"]["thread_id"] for c in checkpointer.list(None)}
    graph = build_graph(checkpointer)
    out = [(tid, tuple(graph.get_state({"configurable": {"thread_id": tid}}).next))
           for tid in threads]
    return sorted(out, reverse=True)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    _load_env()
    config.ensure_dirs()

    checkpointer = default_checkpointer()
    if args.list:
        rows = list_threads(checkpointer)
        if not rows:
            print("no checkpointed runs")
        for tid, nxt in rows:
            where = f"PAUSED at {', '.join(nxt)}" if nxt else "finished"
            print(f"  {tid}  {where}")
        return

    logfire = _configure_logfire()
    run_id = args.resume or args.thread or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    cfg = {"configurable": {"thread_id": run_id}, "recursion_limit": 50}
    graph = build_graph(checkpointer)

    if args.resume:
        from langgraph.types import Command

        if tuple(graph.get_state(cfg).next) != ("gate",):
            print(f"run {run_id} is not paused at the gate — nothing to resume")
            raise SystemExit(1)
        graph_input = Command(resume="approve" if args.approve else "reject")
    else:
        graph_input = {"run_id": run_id, "rejects": [], "spent_usd": 0.0, "stats": {}}

    t0 = time.monotonic()
    span = logfire.span("ingestion_run", run_id=run_id, resumed=bool(args.resume)) if logfire else None
    if span:
        span.__enter__()
    try:
        graph.invoke(graph_input, cfg)
    finally:
        if span:
            span.__exit__(None, None, None)

    snapshot = graph.get_state(cfg)
    if tuple(snapshot.next) == ("gate",):
        pending = snapshot.tasks[0].interrupts[0].value if snapshot.tasks and snapshot.tasks[0].interrupts else {}
        print(f"  pending {pending.get('pending', '?')} chunks from {pending.get('docs', '?')} docs · "
              f"sample {pending.get('sample', [])}")
        print(f"PAUSED at gate · run_id {run_id} · resume: "
              f"python -m ingestion.run --resume {run_id} --approve")
        return

    final = snapshot.values
    if final.get("stats", {}).get("approved") is False:
        # A rejected run indexed nothing; rewriting the public manifest would make the
        # /pipeline page describe a corpus that was never served.
        print(f"run {run_id} rejected at gate · nothing indexed · manifest unchanged")
        return
    # On a resumed run this is the resume segment only; the paused half was timed then.
    duration = round(time.monotonic() - t0, 1)
    parsed = final.get("parsed", [])
    rejects = final.get("rejects", [])
    accepted = final.get("accepted", [])
    reasons = Counter(r["reason"] for r in rejects)

    # Figure gallery (sub-project A) — safe: only thumbnails + captions, no raw content.
    figures = []
    for p in parsed:
        for b in p.get("blocks", []):
            meta = b.get("meta") or {}
            if b.get("kind") != "image" or not meta.get("thumb"):
                continue
            figures.append({
                "doc_id": p["source_id"],
                "title": p["title"],
                "page": b.get("page", 0),
                "thumb": meta["thumb"],
                "caption": b.get("text", "")[:500],
                "vision": bool(meta.get("vision")),
                "source": p["pdf_url"],
            })

    manifest = {
        "_note": ("Public run manifest of the Tier-3 agentic ingestion pipeline. "
                  "Safe aggregates + provenance only; raw PDFs live in S3, not here."),
        "run_id": run_id,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
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
            "figures_captioned": final.get("stats", {}).get("figures_captioned", len(figures)),
            "tables": sum(p.get("n_tables", 0) for p in parsed),
            "with_math": sum(1 for p in parsed if p.get("has_math")),
            "indexed": final.get("indexed", 0),
            "spent_usd": round(final.get("spent_usd", 0.0), 4),
            "duration_s": duration,
        },
        "rejects_by_reason": dict(reasons),
        "budget_usd": config.TOKEN_BUDGET_USD,
        "figures": figures,
        "docs": [
            {
                "id": p["source_id"],
                "title": p["title"],
                "source": p["pdf_url"],
                "pages": p.get("n_pages", 0),
                "images": p.get("n_images", 0),
                "figures_captioned": p.get("n_captioned", 0),
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
          f"figures captioned {s['figures_captioned']} · tables {s['tables']} · math-docs {s['with_math']}")
    print(f"  chunks {s['chunks']} → accepted {s['accepted']} (rejected {s['rejected']}: {dict(reasons)})")
    print(f"  gate: approved={final.get('stats', {}).get('approved')} "
          f"by {final.get('stats', {}).get('approved_by')}")
    print(f"  indexed {s['indexed']} into '{config.COLLECTION}' · spent ${s['spent_usd']}")
    print(f"  manifest → {config.MANIFEST_PATH}")


if __name__ == "__main__":
    main()

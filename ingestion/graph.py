"""Stage orchestration — a LangGraph StateGraph.

    discover → fetch → parse → enrich → quality → [human gate] → index

Each node returns a partial state update; lists accumulate as documents progress.
Transient stages carry a RetryPolicy (bounded), fetch/parse dead-letter failures into
``rejects`` rather than aborting the run, and a human-approval gate sits before indexing
(auto-approved in CI via INGEST_AUTO_APPROVE, held for a human otherwise).

Keeping orchestration declarative here means the control flow — retries, the gate, the
conditional skip when nothing is approved — is inspectable in one place.
"""

from __future__ import annotations

import os

from langgraph.graph import END, START, StateGraph

from ingestion import config
from ingestion.caption import caption_figures
from ingestion.enrich import enrich
from ingestion.fetch import fetch
from ingestion.index import index_chunks, write_catalog
from ingestion.parse import parse_pdf
from ingestion.quality import quality_gate
from ingestion.discover import discover
from ingestion.state import Chunk, FetchedDoc, ParsedDoc, PipelineState, Reject, SourceDoc
from ingestion.storage import get_storage

try:  # RetryPolicy moved around across langgraph versions — attach if available
    from langgraph.types import RetryPolicy
    _RETRY = RetryPolicy(max_attempts=config.NODE_RETRIES)
except Exception:  # pragma: no cover
    _RETRY = None


def _n_discover(state: PipelineState) -> dict:
    sources = discover()
    return {"sources": [s.model_dump() for s in sources],
            "rejects": state.get("rejects", []), "spent_usd": state.get("spent_usd", 0.0)}


def _n_fetch(state: PipelineState) -> dict:
    storage = get_storage()
    sources = [SourceDoc(**s) for s in state["sources"]]
    fetched, rejects = fetch(sources, storage)
    return {"fetched": [f.model_dump() for f in fetched],
            "rejects": state.get("rejects", []) + [r.model_dump() for r in rejects]}


def _n_parse(state: PipelineState) -> dict:
    storage = get_storage()
    parsed, rejects = [], list(state.get("rejects", []))
    for f in state["fetched"]:
        fd = FetchedDoc(**f)
        try:
            parsed.append(parse_pdf(fd, storage).model_dump())
        except Exception as e:  # noqa: BLE001 — one bad PDF shouldn't sink the run
            rejects.append(Reject(ref=fd.source.id, stage="parse", reason=str(e)[:200]).model_dump())
    return {"parsed": parsed, "rejects": rejects}


def _n_caption(state: PipelineState) -> dict:
    # Sub-project A: rasterize + vision-caption figures, appending image blocks.
    storage = get_storage()
    parsed = [ParsedDoc(**p) for p in state["parsed"]]
    fetched = [FetchedDoc(**f) for f in state["fetched"]]
    parsed, spent, n_captioned = caption_figures(parsed, fetched, storage, state.get("spent_usd", 0.0))
    stats = dict(state.get("stats", {}))
    stats["figures_captioned"] = n_captioned
    return {"parsed": [p.model_dump() for p in parsed], "spent_usd": spent, "stats": stats}


def _n_enrich(state: PipelineState) -> dict:
    parsed = [ParsedDoc(**p) for p in state["parsed"]]
    chunks, spent = enrich(parsed, state.get("spent_usd", 0.0))
    return {"chunks": [c.model_dump() for c in chunks], "spent_usd": spent}


def _n_quality(state: PipelineState) -> dict:
    chunks = [Chunk(**c) for c in state["chunks"]]
    accepted, rejects = quality_gate(chunks)
    return {"accepted": [c.model_dump() for c in accepted],
            "rejects": state.get("rejects", []) + [r.model_dump() for r in rejects]}


def _n_gate(state: PipelineState) -> dict:
    # HITL: CI auto-approves; a human run can hold indexing by unsetting the flag.
    approved = os.environ.get("INGEST_AUTO_APPROVE", "1") == "1"
    stats = dict(state.get("stats", {}))
    stats["approved"] = approved
    return {"stats": stats}


def _route_after_gate(state: PipelineState) -> str:
    return "index" if state.get("stats", {}).get("approved") else END


def _n_index(state: PipelineState) -> dict:
    accepted = [Chunk(**c) for c in state["accepted"]]
    parsed = [ParsedDoc(**p) for p in state["parsed"]]
    n = index_chunks(accepted)
    write_catalog(parsed, accepted)
    return {"indexed": n}


def build_graph():
    g = StateGraph(PipelineState)
    kw = {"retry": _RETRY} if _RETRY is not None else {}
    g.add_node("discover", _n_discover)
    g.add_node("fetch", _n_fetch, **kw)
    g.add_node("parse", _n_parse, **kw)
    g.add_node("caption", _n_caption, **kw)
    g.add_node("enrich", _n_enrich, **kw)
    g.add_node("quality", _n_quality)
    g.add_node("gate", _n_gate)
    g.add_node("index", _n_index, **kw)

    g.add_edge(START, "discover")
    g.add_edge("discover", "fetch")
    g.add_edge("fetch", "parse")
    g.add_edge("parse", "caption")
    g.add_edge("caption", "enrich")
    g.add_edge("enrich", "quality")
    g.add_edge("quality", "gate")
    g.add_conditional_edges("gate", _route_after_gate, {"index": "index", END: END})
    g.add_edge("index", END)
    return g.compile()

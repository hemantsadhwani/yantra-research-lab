"""Stage 4 — Enrich (agentic). Chunk each document, then add LLM-generated metadata.

Chunking is deterministic (word windows with overlap) — cheap and reproducible. The
*agentic* part is one bounded Haiku call per document that returns a one-line summary +
topic tags, which are attached to every chunk of that doc (doc-level enrichment keeps
cost at pennies for 30 papers). A hard USD budget stops enrichment early and falls back
to deterministic metadata rather than overspending.

Image blocks that carry a vision caption (from the ``caption`` stage) ARE indexed here:
each becomes one figure chunk (``kind="image"``) embedded by its caption, with its S3 path
and thumbnail preserved — that's the caption-based multimodal retrieval. Uncaptioned image
blocks (no text) are still skipped.
"""

from __future__ import annotations

import hashlib

from ingestion import config
from ingestion.caption import figure_chunk_sha
from ingestion.llm import complete_json
from ingestion.state import Chunk, ParsedDoc

_ENRICH_SYSTEM = (
    "You label quant-finance research for a methodology knowledge base. "
    "Given a paper's title and abstract, reply with ONLY a JSON object: "
    '{"summary": "<=25 words, factual", "topics": ["3-6 short lowercase tags"]}. '
    "No prose, no code fences."
)


def _windows(text: str) -> list[str]:
    words = text.split()
    if not words:
        return []
    step = max(1, config.CHUNK_WORDS - config.OVERLAP_WORDS)
    out = []
    for start in range(0, len(words), step):
        w = words[start : start + config.CHUNK_WORDS]
        if w:
            out.append(" ".join(w))
        if start + config.CHUNK_WORDS >= len(words):
            break
    return out


def _doc_metadata(parsed: ParsedDoc, spent: float) -> tuple[str, list[str], float]:
    """One bounded LLM call for summary + topics. Falls back to '' / [] over budget."""
    if spent >= config.TOKEN_BUDGET_USD:
        return "", [], 0.0
    user = f"Title: {parsed.title}\n\nAbstract: {parsed.blocks[0].text[:1500] if parsed.blocks else ''}"
    data, cost = complete_json(
        _ENRICH_SYSTEM, user, model=config.ENRICH_MODEL, max_tokens=config.ENRICH_MAX_TOKENS
    )
    if not data:
        return "", [], cost
    summary = str(data.get("summary", ""))[:300]
    topics = [str(t).lower().strip()[:30] for t in (data.get("topics") or [])][:6]
    return summary, topics, cost


def enrich(parsed_docs: list[ParsedDoc], start_spent: float = 0.0) -> tuple[list[Chunk], float]:
    """Return (chunks, total_spent_usd). Chunks carry doc-level summary + topics."""
    chunks: list[Chunk] = []
    spent = start_spent
    cid = 0
    for parsed in parsed_docs:
        summary, topics, cost = _doc_metadata(parsed, spent)
        spent += cost
        for block in parsed.blocks:
            if block.kind == "image":
                # Captioned figure → one indexable chunk embedded by its caption.
                # Uncaptioned image blocks (e.g. raw rasters from parse) are skipped.
                cap = block.text.strip()
                if len(cap) < 20:
                    continue
                chunks.append(
                    Chunk(
                        id=cid, doc_id=parsed.source_id, title=parsed.title,
                        source_url=parsed.pdf_url, text=cap, kind="image", page=block.page,
                        sha256=figure_chunk_sha(parsed.source_id, block.page, cap),
                        topics=topics, summary=summary, image_path=block.image_path,
                    )
                )
                cid += 1
                continue
            texts = _windows(block.text) if block.kind == "text" else [block.text]
            for piece in texts:
                piece = piece.strip()
                if len(piece) < 40:  # skip fragments
                    continue
                chunks.append(
                    Chunk(
                        id=cid,
                        doc_id=parsed.source_id,
                        title=parsed.title,
                        source_url=parsed.pdf_url,
                        text=piece,
                        kind=block.kind,
                        page=block.page,
                        sha256=hashlib.sha256(piece.encode("utf-8")).hexdigest(),
                        topics=topics,
                        summary=summary,
                    )
                )
                cid += 1
    return chunks, spent

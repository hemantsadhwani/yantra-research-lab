"""Stage 6 — Index + catalog (gold + lineage).

Embeds accepted chunks with the SAME model the serving API queries with
(``BAAI/bge-small-en-v1.5``, 384-d) — matching train/serve embeddings is non-negotiable
or retrieval silently degrades. Upserts to a SEPARATE Qdrant collection
(``research_corpus``) so the live ``methodology`` index the chatbot uses is never
disturbed (blue/green data). Point ids are derived from the content hash, so re-running
is idempotent — a daily refresh overwrites, never duplicates.

Also writes a lineage catalog: for each doc, where it came from and what came out of it.
"""

from __future__ import annotations

import json
import os

from ingestion import config
from ingestion.state import Chunk, ParsedDoc

_embedder = None


def _embed(texts: list[str]) -> list[list[float]]:
    global _embedder
    if _embedder is None:
        from fastembed import TextEmbedding

        _embedder = TextEmbedding(model_name=config.EMBED_MODEL)
    return [list(v) for v in _embedder.embed(texts)]


def _client():
    from qdrant_client import QdrantClient

    url = os.environ.get("QDRANT_URL")
    if url:
        return QdrantClient(url=url, api_key=os.environ.get("QDRANT_API_KEY"))
    # local embedded fallback for offline dev
    path = str(config.DATA_DIR / "qdrant")
    return QdrantClient(path=path)


def _point_id(sha256: str) -> int:
    # stable 63-bit id from the content hash → idempotent upserts
    return int(sha256[:16], 16) & 0x7FFFFFFFFFFFFFFF


def index_chunks(chunks: list[Chunk]) -> int:
    """Embed + upsert accepted chunks into the research_corpus collection. Returns count."""
    if not chunks:
        return 0
    from qdrant_client.models import Distance, PointStruct, VectorParams

    client = _client()
    vectors = _embed([c.text for c in chunks])
    dim = len(vectors[0])

    existing = {c.name for c in client.get_collections().collections}
    if config.COLLECTION not in existing:
        client.create_collection(
            collection_name=config.COLLECTION,
            vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
        )

    points = [
        PointStruct(
            id=_point_id(c.sha256),
            vector=vectors[i],
            payload={
                "text": c.text,
                "title": c.title,
                "source": c.source_url,
                "doc_id": c.doc_id,
                "page": c.page,
                "kind": c.kind,
                "topics": c.topics,
                "summary": c.summary,
                "image_path": c.image_path,
            },
        )
        for i, c in enumerate(chunks)
    ]
    # batch to keep request sizes sane
    for i in range(0, len(points), 128):
        client.upsert(collection_name=config.COLLECTION, points=points[i : i + 128])
    return len(points)


def write_catalog(parsed_docs: list[ParsedDoc], accepted: list[Chunk]) -> None:
    """Persist lineage: per-doc provenance + what survived into the index."""
    by_doc: dict[str, int] = {}
    for c in accepted:
        by_doc[c.doc_id] = by_doc.get(c.doc_id, 0) + 1
    catalog = {
        "collection": config.COLLECTION,
        "embed_model": config.EMBED_MODEL,
        "docs": [
            {
                "id": d.source_id,
                "title": d.title,
                "source": d.pdf_url,
                "pages": d.n_pages,
                "images": d.n_images,
                "figures_captioned": d.n_captioned,
                "tables": d.n_tables,
                "has_math": d.has_math,
                "ocr_used": d.ocr_used,
                "chunks_indexed": by_doc.get(d.source_id, 0),
            }
            for d in parsed_docs
        ],
    }
    config.CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.CATALOG_PATH.write_text(json.dumps(catalog, indent=2), encoding="utf-8")

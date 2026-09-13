"""Retriever interface — one contract, swappable engines.

A single abstract ``Retriever`` (``index`` + ``search``) with a concrete
``QdrantRetriever``. The interface is the boundary the RAG code depends on, so the
vector store can be swapped without touching the chatbot:

- ``QdrantRetriever`` — qdrant-client in local, on-disk mode (no server) for the demo.
  The same class points at **Qdrant Cloud** (or a Qdrant container) by URL later, and a
  future ``OpenSearchRetriever`` slots in behind the same contract for multi-tenant scale.

The index persists to disk during ``ingest.py`` so the API process can reopen it without
re-embedding the corpus.

Two collections, both read. ``ingest.py`` writes the chatbot's own corpus to
``QDRANT_COLLECTION`` (``methodology``: seed notes + strategy-book docs). The Tier-3
ingestion pipeline writes arXiv paper chunks to ``research_corpus`` with the same
embedding model and a compatible payload (``text``/``title``/``source``, 63-bit int
ids). ``search()`` queries every collection in ``QDRANT_READ_COLLECTIONS`` and merges by
score, so the papers are citable. A collection that does not exist (local dev before
the pipeline has run) is skipped with a warning, not fatal.
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from embeddings import EMBED_DIM, embed, embed_one

_DEFAULT_QDRANT_PATH = os.environ.get(
    "QDRANT_PATH", str(Path(__file__).parent / ".qdrant")
)
_COLLECTION = os.environ.get("QDRANT_COLLECTION", "methodology")
# Read side: the write collection first, then the ingestion pipeline's corpus.
_READ_COLLECTIONS = [
    c.strip()
    for c in os.environ.get(
        "QDRANT_READ_COLLECTIONS", f"{_COLLECTION},research_corpus"
    ).split(",")
    if c.strip()
]

log = logging.getLogger(__name__)


@dataclass
class Chunk:
    """A unit of retrievable text plus provenance."""

    id: int
    text: str
    title: str
    source: str = ""
    score: float = 0.0
    collection: str = ""


class Retriever(ABC):
    """Abstract retriever: index a corpus, then search it."""

    @abstractmethod
    def index(self, docs: list[Chunk]) -> None:
        """Embed and persist the given chunks (replacing any existing index)."""

    @abstractmethod
    def search(self, query: str, k: int = 4) -> list[Chunk]:
        """Return the top-k most similar chunks to ``query`` (highest score first)."""

    def load(self) -> None:
        """Reopen a previously built index. Default: no-op (Qdrant opens on init)."""


# --------------------------------------------------------------------------- #
# Qdrant (local on-disk mode; same class targets Qdrant Cloud by URL later)
# --------------------------------------------------------------------------- #
class QdrantRetriever(Retriever):
    def __init__(
        self,
        path: str | None = None,
        collection: str = _COLLECTION,
        read_collections: list[str] | None = None,
    ):
        from qdrant_client import QdrantClient

        self.path = path or _DEFAULT_QDRANT_PATH
        self.collection = collection
        self.read_collections = _with_primary(collection, read_collections or _READ_COLLECTIONS)
        # Local mode: an embedded, file-backed collection — no server process.
        # To scale, swap this for QdrantClient(url=..., api_key=...) — no other change.
        url = os.environ.get("QDRANT_URL")
        if url:
            self.client = QdrantClient(url=url, api_key=os.environ.get("QDRANT_API_KEY"))
        else:
            Path(self.path).mkdir(parents=True, exist_ok=True)
            self.client = QdrantClient(path=self.path)

    def index(self, docs: list[Chunk]) -> None:
        from qdrant_client.models import Distance, PointStruct, VectorParams

        vectors = embed([d.text for d in docs])
        size = len(vectors[0]) if vectors else EMBED_DIM
        self.client.recreate_collection(
            collection_name=self.collection,
            vectors_config=VectorParams(size=size, distance=Distance.COSINE),
        )
        points = [
            PointStruct(
                id=d.id,
                vector=vectors[i],
                payload={"text": d.text, "title": d.title, "source": d.source},
            )
            for i, d in enumerate(docs)
        ]
        self.client.upsert(collection_name=self.collection, points=points)

    def _query(self, collection: str, qv: list[float], k: int):
        try:
            return self.client.query_points(collection_name=collection, query=qv, limit=k).points
        except AttributeError:  # older qdrant-client without query_points
            return self.client.search(collection_name=collection, query_vector=qv, limit=k)

    def search(self, query: str, k: int = 4) -> list[Chunk]:
        """Top-k across every read collection, merged by cosine score.

        Scores are comparable across collections because both are embedded with the
        same model. Each collection is asked for k so a strong corpus cannot be
        starved by a weak one; the merged list is then cut to k.
        """
        qv = embed_one(query)
        out: list[Chunk] = []
        for collection in self.read_collections:
            try:
                hits = self._query(collection, qv, k)
            except Exception as e:  # noqa: BLE001 - missing collection, transient cluster error
                # One absent or failing collection must not take down retrieval
                # from the others; the caller already degrades gracefully to none.
                log.warning("retrieval skipped collection %r: %s", collection, e)
                continue
            for h in hits:
                payload = h.payload or {}
                out.append(
                    Chunk(
                        id=int(h.id),
                        text=payload.get("text", ""),
                        title=payload.get("title", ""),
                        source=payload.get("source", ""),
                        score=float(h.score) if h.score is not None else 0.0,
                        collection=collection,
                    )
                )
        out.sort(key=lambda c: c.score, reverse=True)
        return out[:k]


def _with_primary(primary: str, reads: list[str]) -> list[str]:
    """The write collection is always read, and read first."""
    reads = [c for c in reads if c != primary]
    return [primary, *reads]


# --------------------------------------------------------------------------- #
# Factory
# --------------------------------------------------------------------------- #
def get_retriever() -> Retriever:
    """Construct the retriever. Qdrant local by default; set QDRANT_URL for Qdrant Cloud."""
    return QdrantRetriever()

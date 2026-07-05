"""Retriever interface — one contract, swappable engines.

A single abstract ``Retriever`` (``index`` + ``search``) with a concrete
``QdrantRetriever``. The interface is the boundary the RAG code depends on, so the
vector store can be swapped without touching the chatbot:

- ``QdrantRetriever`` — qdrant-client in local, on-disk mode (no server) for the demo.
  The same class points at **Qdrant Cloud** (or a Qdrant container) by URL later, and a
  future ``OpenSearchRetriever`` slots in behind the same contract for multi-tenant scale.

The index persists to disk during ``ingest.py`` so the API process can reopen it without
re-embedding the corpus.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from embeddings import EMBED_DIM, embed, embed_one

_DEFAULT_QDRANT_PATH = os.environ.get(
    "QDRANT_PATH", str(Path(__file__).parent / ".qdrant")
)
_COLLECTION = os.environ.get("QDRANT_COLLECTION", "methodology")


@dataclass
class Chunk:
    """A unit of retrievable text plus provenance."""

    id: int
    text: str
    title: str
    source: str = ""
    score: float = 0.0


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
    def __init__(self, path: str | None = None, collection: str = _COLLECTION):
        from qdrant_client import QdrantClient

        self.path = path or _DEFAULT_QDRANT_PATH
        self.collection = collection
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

    def search(self, query: str, k: int = 4) -> list[Chunk]:
        qv = embed_one(query)
        try:
            hits = self.client.query_points(
                collection_name=self.collection, query=qv, limit=k
            ).points
        except AttributeError:  # older qdrant-client without query_points
            hits = self.client.search(
                collection_name=self.collection, query_vector=qv, limit=k
            )
        out: list[Chunk] = []
        for h in hits:
            payload = h.payload or {}
            out.append(
                Chunk(
                    id=int(h.id),
                    text=payload.get("text", ""),
                    title=payload.get("title", ""),
                    source=payload.get("source", ""),
                    score=float(h.score) if h.score is not None else 0.0,
                )
            )
        return out


# --------------------------------------------------------------------------- #
# Factory
# --------------------------------------------------------------------------- #
def get_retriever() -> Retriever:
    """Construct the retriever. Qdrant local by default; set QDRANT_URL for Qdrant Cloud."""
    return QdrantRetriever()

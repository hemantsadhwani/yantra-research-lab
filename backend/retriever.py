"""Retriever interface — one contract, swappable engines.

A single abstract ``Retriever`` (``index`` + ``search``) with two concrete engines,
``QdrantRetriever`` (the default) and ``FaissRetriever`` (``VECTOR_BACKEND=faiss``).
The interface is the boundary the RAG code depends on, so the vector store can be
swapped without touching the chatbot:

- ``QdrantRetriever`` — qdrant-client in local, on-disk mode (no server) for the demo.
  The same class points at **Qdrant Cloud** (or a Qdrant container) by URL later, and a
  future ``OpenSearchRetriever`` slots in behind the same contract for multi-tenant scale.
- ``FaissRetriever`` — an exact inner-product FAISS index over unit vectors (= cosine),
  persisted as two files in ``backend/.faiss/`` next to ``backend/.qdrant/``. Same
  embedding model, same ``Chunk`` out. It holds only the chatbot's own corpus
  (``methodology``); the arXiv ``research_corpus`` lives in Qdrant and is not mirrored.

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
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from embeddings import EMBED_DIM, embed, embed_one

_DEFAULT_QDRANT_PATH = os.environ.get(
    "QDRANT_PATH", str(Path(__file__).parent / ".qdrant")
)
_DEFAULT_FAISS_PATH = os.environ.get("FAISS_PATH", str(Path(__file__).parent / ".faiss"))
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


# --------------------------------------------------------------------------- #
# FAISS (in-process, file-persisted; VECTOR_BACKEND=faiss)
# --------------------------------------------------------------------------- #
class FaissRetriever(Retriever):
    """Exact cosine search with FAISS ``IndexFlatIP`` over L2-normalised vectors.

    Persisted as ``index.faiss`` (vectors + int64 chunk ids) and ``chunks.json``
    (id -> text/title/source). ``faiss`` and ``numpy`` are imported lazily, so importing
    this module never needs them. ``embed_fn`` defaults to the backend's fastembed
    model; tests and the offline RAGAS harness pass a deterministic one.
    """

    INDEX_FILE = "index.faiss"
    CHUNKS_FILE = "chunks.json"

    def __init__(
        self,
        path: str | None = None,
        collection: str = _COLLECTION,
        embed_fn: Callable[[list[str]], list[list[float]]] | None = None,
    ):
        self.path = Path(path or _DEFAULT_FAISS_PATH)
        self.collection = collection
        self._embed_fn = embed_fn
        self._index = None
        self._chunks: dict[int, dict] = {}

    def _embed(self, texts: list[str]):
        import numpy as np

        # Look ``embed`` up at call time so a monkeypatched module function is honoured.
        vecs = (self._embed_fn or embed)(texts)
        arr = np.asarray(vecs, dtype="float32")
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return arr / norms  # unit vectors: inner product == cosine

    def index(self, docs: list[Chunk]) -> None:
        import json

        import faiss
        import numpy as np

        vectors = self._embed([d.text for d in docs])
        dim = vectors.shape[1] if len(docs) else EMBED_DIM
        index = faiss.IndexIDMap2(faiss.IndexFlatIP(dim))
        if len(docs):
            index.add_with_ids(vectors, np.asarray([d.id for d in docs], dtype="int64"))
        self.path.mkdir(parents=True, exist_ok=True)
        faiss.write_index(index, str(self.path / self.INDEX_FILE))
        self._chunks = {
            d.id: {"text": d.text, "title": d.title, "source": d.source} for d in docs
        }
        (self.path / self.CHUNKS_FILE).write_text(
            json.dumps({str(k): v for k, v in self._chunks.items()}), encoding="utf-8"
        )
        self._index = index

    def load(self) -> None:
        import json

        import faiss

        self._index = faiss.read_index(str(self.path / self.INDEX_FILE))
        raw = json.loads((self.path / self.CHUNKS_FILE).read_text(encoding="utf-8"))
        self._chunks = {int(k): v for k, v in raw.items()}

    def search(self, query: str, k: int = 4) -> list[Chunk]:
        if self._index is None:
            self.load()
        if self._index.ntotal == 0:
            return []
        scores, ids = self._index.search(self._embed([query]), min(k, self._index.ntotal))
        out: list[Chunk] = []
        for score, cid in zip(scores[0], ids[0], strict=True):
            if cid < 0:  # FAISS pads with -1 when fewer than k vectors exist
                continue
            payload = self._chunks.get(int(cid), {})
            out.append(
                Chunk(
                    id=int(cid),
                    text=payload.get("text", ""),
                    title=payload.get("title", ""),
                    source=payload.get("source", ""),
                    score=float(score),
                    collection=self.collection,
                )
            )
        return out


def _with_primary(primary: str, reads: list[str]) -> list[str]:
    """The write collection is always read, and read first."""
    reads = [c for c in reads if c != primary]
    return [primary, *reads]


# --------------------------------------------------------------------------- #
# Factory
# --------------------------------------------------------------------------- #
VECTOR_BACKENDS = ("qdrant", "faiss")


def get_retriever(backend: str | None = None) -> Retriever:
    """Construct the retriever named by ``backend`` or ``$VECTOR_BACKEND``.

    ``qdrant`` (the default): local on-disk, or Qdrant Cloud when QDRANT_URL is set.
    ``faiss``: the on-disk FAISS index in ``backend/.faiss`` (build it with
    ``VECTOR_BACKEND=faiss python ingest.py``).
    """
    name = (backend or os.environ.get("VECTOR_BACKEND") or "qdrant").strip().lower()
    if name == "qdrant":
        return QdrantRetriever()
    if name == "faiss":
        return FaissRetriever()
    raise ValueError(f"unknown VECTOR_BACKEND={name!r}; expected one of {VECTOR_BACKENDS}")


if __name__ == "__main__":  # python retriever.py "what is a drawdown?"
    import sys

    q = " ".join(sys.argv[1:]) or "what is a maximum drawdown?"
    r = get_retriever()
    r.load()
    print(f"VECTOR_BACKEND={os.environ.get('VECTOR_BACKEND', 'qdrant')} query={q!r}")
    for c in r.search(q, k=3):
        print(f"  {c.score:.3f}  [{c.collection}] {c.title}  ({c.source})")

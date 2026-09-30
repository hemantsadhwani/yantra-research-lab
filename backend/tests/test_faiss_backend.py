"""FAISS vs Qdrant behind one ``Retriever`` interface: same top-1 on a tiny corpus.

Both engines run for real (FAISS in-process, Qdrant in local on-disk mode under
``tmp_path``). Embeddings are a deterministic hashed bag-of-words stub, so the test is
offline and needs no fastembed model download. Keyword routing (``books.select_docs``)
must not care which vector backend is selected.
"""

import hashlib
import math
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import books
import retriever
from retriever import Chunk, FaissRetriever, QdrantRetriever

DIM = 64
_TOK = re.compile(r"[a-z0-9]+")


def _stub_vec(text: str) -> list[float]:
    vec = [0.0] * DIM
    for tok in _TOK.findall(text.lower()):
        h = int.from_bytes(hashlib.blake2b(tok.encode(), digest_size=8).digest(), "big")
        vec[h % DIM] += 1.0
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def _stub_embed(texts):
    return [_stub_vec(t) for t in texts]


CORPUS = [
    Chunk(id=0, title="Drawdown", text="drawdown peak trough equity curve decline underwater"),
    Chunk(id=1, title="Sharpe", text="sharpe ratio excess return divided by volatility annualised"),
    Chunk(id=2, title="Greeks", text="options greeks delta gamma theta vega sensitivity premium"),
    Chunk(id=3, title="Walk-forward", text="walk forward validation out of sample windows rolling"),
    Chunk(id=4, title="Z-score", text="zscore bollinger bands mean reversion standard deviations"),
    Chunk(id=5, title="Parity", text="backtesting parity live fills slippage costs simulation"),
]

QUERIES = {
    "what is a drawdown from peak to trough?": 0,
    "explain the sharpe ratio and volatility": 1,
    "how do delta and gamma greeks work for options?": 2,
}


@pytest.fixture
def stub_embeddings(monkeypatch):
    monkeypatch.setattr(retriever, "embed", _stub_embed)
    monkeypatch.setattr(retriever, "embed_one", lambda q: _stub_vec(q))
    monkeypatch.delenv("QDRANT_URL", raising=False)


def test_faiss_and_qdrant_agree_on_top1(stub_embeddings, tmp_path):
    pytest.importorskip("faiss")
    pytest.importorskip("qdrant_client")
    faiss_r = FaissRetriever(path=str(tmp_path / "faiss"))
    faiss_r.index(CORPUS)
    qdrant_r = QdrantRetriever(path=str(tmp_path / "qdrant"), collection="t",
                               read_collections=["t"])
    qdrant_r.index(CORPUS)
    for q, want in QUERIES.items():
        f, qd = faiss_r.search(q, k=3), qdrant_r.search(q, k=3)
        assert f[0].id == qd[0].id == want, (q, [c.id for c in f], [c.id for c in qd])
        assert f[0].score == pytest.approx(qd[0].score, abs=1e-4)  # both are cosine
        assert f[0].collection == "methodology" and f[0].title == CORPUS[want].title


def test_faiss_index_persists_and_reloads(stub_embeddings, tmp_path):
    pytest.importorskip("faiss")
    FaissRetriever(path=str(tmp_path)).index(CORPUS)
    assert (tmp_path / "index.faiss").exists() and (tmp_path / "chunks.json").exists()
    fresh = FaissRetriever(path=str(tmp_path))  # new process-equivalent: nothing in memory
    fresh.load()
    hits = fresh.search("walk forward out of sample", k=10)
    assert hits[0].id == 3 and len(hits) == len(CORPUS)  # k is capped at the corpus size
    assert [h.score for h in hits] == sorted((h.score for h in hits), reverse=True)


def test_factory_default_is_qdrant_and_faiss_is_opt_in(monkeypatch):
    made = []
    monkeypatch.setattr(retriever, "QdrantRetriever", lambda: made.append("qdrant") or "Q")
    monkeypatch.delenv("VECTOR_BACKEND", raising=False)
    assert retriever.get_retriever() == "Q"
    monkeypatch.setenv("VECTOR_BACKEND", "faiss")
    assert isinstance(retriever.get_retriever(), FaissRetriever)
    monkeypatch.setenv("VECTOR_BACKEND", "chroma")
    with pytest.raises(ValueError):
        retriever.get_retriever()
    assert made == ["qdrant"]


@pytest.mark.parametrize("backend", ["qdrant", "faiss"])
def test_keyword_routing_ignores_vector_backend(monkeypatch, backend):
    monkeypatch.setenv("VECTOR_BACKEND", backend)
    docs = books.load_books()
    picked = books.select_docs("what is the sensex expiry book pnl?", docs)
    assert any(d.product == "sensex-expiry" for d in picked)
    assert books.select_docs("what is a sharpe ratio?", docs) == []

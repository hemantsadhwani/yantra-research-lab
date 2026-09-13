"""Multi-collection search: merge by score, tolerate a missing collection, cap at k.

No Qdrant, no fastembed: the client is a fake and ``embed_one`` is monkeypatched, so
this runs anywhere ``test_guardrails`` does.
"""

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import retriever


class _FakeClient:
    """query_points() answers per collection; unknown collections raise like Qdrant does."""

    def __init__(self, data: dict[str, list[tuple[int, float, str]]]):
        self.data = data
        self.calls: list[str] = []

    def query_points(self, collection_name, query, limit):
        self.calls.append(collection_name)
        if collection_name not in self.data:
            raise RuntimeError(f"Not found: Collection `{collection_name}` does not exist")
        pts = [
            SimpleNamespace(id=i, score=s, payload={"text": f"text {t}", "title": t, "source": ""})
            for i, s, t in self.data[collection_name]
        ]
        return SimpleNamespace(points=pts[:limit])


def _retriever(monkeypatch, data, reads):
    monkeypatch.setattr(retriever, "embed_one", lambda q: [0.0] * 3)
    r = object.__new__(retriever.QdrantRetriever)
    r.collection = reads[0]
    r.read_collections = list(reads)
    r.client = _FakeClient(data)
    return r


def test_merges_across_collections_by_score(monkeypatch):
    r = _retriever(
        monkeypatch,
        {
            "methodology": [(1, 0.80, "Drawdown"), (2, 0.40, "Sharpe")],
            "research_corpus": [(11, 0.90, "Paper A"), (12, 0.70, "Paper B"), (13, 0.10, "Paper C")],
        },
        ["methodology", "research_corpus"],
    )
    hits = r.search("anything", k=3)
    assert [h.title for h in hits] == ["Paper A", "Drawdown", "Paper B"]
    assert [h.collection for h in hits] == ["research_corpus", "methodology", "research_corpus"]


def test_missing_collection_is_skipped_not_fatal(monkeypatch):
    r = _retriever(
        monkeypatch,
        {"methodology": [(1, 0.5, "Drawdown")]},
        ["methodology", "research_corpus"],
    )
    hits = r.search("anything", k=4)
    assert [h.title for h in hits] == ["Drawdown"]
    assert r.client.calls == ["methodology", "research_corpus"]


def test_each_collection_asked_for_k_then_cut_to_k(monkeypatch):
    r = _retriever(
        monkeypatch,
        {
            "methodology": [(i, 0.3, f"m{i}") for i in range(10)],
            "research_corpus": [(100 + i, 0.9, f"p{i}") for i in range(10)],
        },
        ["methodology", "research_corpus"],
    )
    hits = r.search("anything", k=4)
    assert len(hits) == 4
    assert all(h.collection == "research_corpus" for h in hits)


def test_write_collection_is_always_read_first():
    assert retriever._with_primary("methodology", ["research_corpus"]) == [
        "methodology",
        "research_corpus",
    ]
    assert retriever._with_primary("methodology", ["research_corpus", "methodology"]) == [
        "methodology",
        "research_corpus",
    ]


def test_default_read_collections_cover_both_corpora():
    assert retriever._READ_COLLECTIONS[:2] == ["methodology", "research_corpus"]

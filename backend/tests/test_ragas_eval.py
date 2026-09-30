"""End-to-end offline RAGAS harness: the chatbot answer path over the real corpus.

Fake answerer + lexical judge + hashed embeddings: this proves the harness runs and the
expected source is retrieved, not answer quality.
"""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)


def test_fake_run_scores_all_twelve_in_range():
    pytest.importorskip("faiss")
    from eval import ragas_eval as rg

    def embed_texts(texts):
        return [rg.hashed_embed(t) for t in texts]

    out = rg.evaluate(rg.load_golden(), rg.ExtractiveFakeProvider(), rg.LexicalJudge(),
                      rg.hashed_embed, embed_texts)
    assert out["n"] == 12
    assert not any(r["refused"] for r in out["rows"])
    for m in rg.METRICS:
        assert 0.0 <= out["means"][m] <= 1.0, m
    assert out["hits"] >= 10  # the expected source doc is in the retrieved context

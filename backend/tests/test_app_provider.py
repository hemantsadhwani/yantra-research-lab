"""/api/chat through the llm_gateway seam — offline, with a scripted FakeProvider.

No API key, no network: the provider factory and the retriever are both stubbed.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

pytest.importorskip("fastapi")

import app as app_mod
from fastapi.testclient import TestClient

from llm_gateway import FakeProvider

ANSWER = "Mean reversion is the tendency of a price to drift back toward its average."


class _NoRetriever:
    def search(self, query, k=4):
        return []


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    provider = FakeProvider([ANSWER], cost_per_call=0.0042)
    monkeypatch.setattr(app_mod, "get_provider", lambda *a, **k: provider)
    monkeypatch.setattr(app_mod, "_provider", None)          # drop any cached provider
    monkeypatch.setattr(app_mod, "get_retriever_cached", lambda: _NoRetriever())
    app_mod._hits.clear()
    return provider


def test_chat_answers_through_the_provider(fake):
    r = TestClient(app_mod.app).post("/api/chat", json={"message": "What is mean reversion?"})
    assert r.status_code == 200
    body = r.json()
    assert body["answer"] == ANSWER
    assert body["refused"] is False
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["schema"] is None and call["cache_system"] is True
    assert "What is mean reversion?" in call["messages"][-1]["content"]


def test_chat_cost_is_the_providers_cost(fake, monkeypatch):
    seen: list[dict] = []
    real = app_mod.obs.set_attributes

    def capture(span_obj, attrs):
        seen.append(dict(attrs))
        return real(span_obj, attrs)

    monkeypatch.setattr(app_mod.obs, "set_attributes", capture)
    r = TestClient(app_mod.app).post("/api/chat", json={"message": "Explain z-score entry"})
    assert r.status_code == 200
    request_attrs = seen[-1]                                  # the chat_request span
    assert request_attrs["est_cost_usd"] == pytest.approx(fake.cost_per_call)
    assert (request_attrs["provider"], request_attrs["model"]) == ("fake", "fake-1")


def test_no_key_keeps_the_not_configured_answer(monkeypatch):
    """The real anthropic provider with no key: friendly 200, never a 500."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(app_mod, "_provider", None)
    monkeypatch.setattr(app_mod, "LLM_PROVIDER", "anthropic")
    monkeypatch.setattr(app_mod, "get_retriever_cached", lambda: _NoRetriever())
    app_mod._hits.clear()
    r = TestClient(app_mod.app).post("/api/chat", json={"message": "What is a drawdown?"})
    assert r.status_code == 200
    assert "not configured" in r.json()["answer"]

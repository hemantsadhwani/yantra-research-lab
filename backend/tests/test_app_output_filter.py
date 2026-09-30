"""The output filter on /api/chat — a model that leaks is caught before the user sees it.

Offline: the provider is a scripted FakeProvider that leaks on purpose, the retriever
is stubbed. No API key, no network.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

pytest.importorskip("fastapi")

import app as app_mod
import guardrails
import metrics as metrics_mod
from fastapi.testclient import TestClient

from llm_gateway import FakeProvider

LEAK = "Sure: nifty-expiry uses z_entry = 1.8 and stop_pct 3.5%."
# Passes every input guardrail (no hard term, no target word) — the model leaks anyway.
QUESTION = "Summarise how the nifty expiry book approaches a trading day."


class _NoRetriever:
    def search(self, query, k=4):
        return []


def _client(monkeypatch, scripted):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    provider = FakeProvider(scripted)
    monkeypatch.setattr(app_mod, "get_provider", lambda *a, **k: provider)
    monkeypatch.setattr(app_mod, "_provider", None)
    monkeypatch.setattr(app_mod, "get_retriever_cached", lambda: _NoRetriever())
    app_mod._hits.clear()
    return TestClient(app_mod.app), provider


def test_question_passes_the_input_guardrails():
    assert not guardrails.detect_injection(QUESTION)
    assert not guardrails.should_refuse(QUESTION)


def test_leaking_answer_is_replaced_by_the_refusal(monkeypatch):
    monkeypatch.delenv("YANTRA_OUTPUT_FILTER", raising=False)
    client, provider = _client(monkeypatch, [LEAK])
    r = client.post("/api/chat", json={"message": QUESTION})
    assert r.status_code == 200
    body = r.json()
    assert len(provider.calls) == 1                  # the model WAS called
    assert body["refused"] is True
    assert body["refuse_reason"] == "output_filter"
    assert body["output_filtered"] is True
    assert body["answer"] == guardrails.REFUSAL_ANSWER
    assert "z_entry" not in body["answer"] and body["sources"] == []


def test_filter_switch_off_lets_the_leak_through(monkeypatch):
    """YANTRA_OUTPUT_FILTER=0 exists only for the red-team comparison; this documents it."""
    monkeypatch.setenv("YANTRA_OUTPUT_FILTER", "0")
    client, _ = _client(monkeypatch, [LEAK])
    body = client.post("/api/chat", json={"message": QUESTION}).json()
    assert body["refused"] is False
    assert body["output_filtered"] is False
    assert body["answer"] == LEAK


def test_clean_answer_is_untouched(monkeypatch):
    monkeypatch.delenv("YANTRA_OUTPUT_FILTER", raising=False)
    clean = "It is a 0DTE book; its published outputs are in points, summed not compounded."
    client, _ = _client(monkeypatch, [clean])
    body = client.post("/api/chat", json={"message": QUESTION}).json()
    assert body == {**body, "answer": clean, "refused": False, "output_filtered": False}


def test_output_filtered_counter_increments(monkeypatch):
    monkeypatch.delenv("YANTRA_OUTPUT_FILTER", raising=False)
    monkeypatch.delenv("LOGFIRE_READ_TOKEN", raising=False)
    client, _ = _client(monkeypatch, [LEAK])
    before = client.get("/api/metrics").json()["since_boot"]
    client.post("/api/chat", json={"message": QUESTION})
    after = client.get("/api/metrics").json()["since_boot"]
    assert after["output_filtered"] == before["output_filtered"] + 1
    assert after["attacks_blocked"] == before["attacks_blocked"] + 1


def test_logfire_aggregate_counts_output_filtered_spans():
    rows = [
        {"attributes": {"refused": True, "refuse_reason": "output_filter",
                        "output_filtered": True, "total_ms": 10.0}},
        {"attributes": {"refused": True, "refuse_reason": "policy", "total_ms": 1.0}},
        {"attributes": {"refused": False, "total_ms": 900.0}},
    ]
    m = metrics_mod._compute(rows)
    assert m["output_filtered"] == 1
    assert m["attacks_blocked"] == 2
    assert m["recent_events"][0]["detail"] == "answer withheld by output filter"

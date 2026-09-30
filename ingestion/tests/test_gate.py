"""The human gate is a real LangGraph interrupt, backed by a checkpointer.

Offline: every stage before the gate is a no-op that drops two fake documents into
state, and ``index`` only records that it ran. No network, no LLM, no Qdrant.
"""

from __future__ import annotations

import pytest

pytest.importorskip("langgraph")

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from ingestion import graph as g

DOCS = [
    {"id": 0, "doc_id": "d1", "title": "Paper one", "source_url": "u1", "text": "a"},
    {"id": 1, "doc_id": "d2", "title": "Paper two", "source_url": "u2", "text": "b"},
]


@pytest.fixture
def indexed(monkeypatch):
    calls: list[int] = []
    monkeypatch.setattr(g, "_n_discover", lambda s: {"sources": [], "rejects": []})
    monkeypatch.setattr(g, "_n_fetch", lambda s: {"fetched": []})
    monkeypatch.setattr(g, "_n_parse", lambda s: {"parsed": []})
    monkeypatch.setattr(g, "_n_caption", lambda s: {})
    monkeypatch.setattr(g, "_n_enrich", lambda s: {"chunks": list(DOCS)})
    monkeypatch.setattr(g, "_n_quality", lambda s: {"accepted": list(DOCS)})

    def fake_index(state):
        calls.append(len(state["accepted"]))
        return {"indexed": len(state["accepted"])}

    monkeypatch.setattr(g, "_n_index", fake_index)
    return calls


def _start(thread: str):
    graph = g.build_graph(InMemorySaver())
    cfg = {"configurable": {"thread_id": thread}}
    graph.invoke({"run_id": thread, "rejects": [], "spent_usd": 0.0, "stats": {}}, cfg)
    return graph, cfg


def test_default_is_the_human_gate(monkeypatch, indexed):
    monkeypatch.delenv("INGEST_AUTO_APPROVE", raising=False)
    graph, cfg = _start("t-pause")
    snap = graph.get_state(cfg)
    assert snap.next == ("gate",)
    payload = snap.tasks[0].interrupts[0].value
    assert payload["pending"] == 2
    assert payload["sample"] == ["Paper one", "Paper two"]
    assert indexed == []                              # nothing indexed while paused


def test_resume_approve_indexes(monkeypatch, indexed):
    monkeypatch.delenv("INGEST_AUTO_APPROVE", raising=False)
    graph, cfg = _start("t-approve")
    graph.invoke(Command(resume="approve"), cfg)
    snap = graph.get_state(cfg)
    assert snap.next == ()
    assert indexed == [2]
    assert snap.values["stats"] == {"approved": True, "approved_by": "human"}
    assert snap.values["indexed"] == 2


def test_resume_reject_does_not_index(monkeypatch, indexed):
    monkeypatch.delenv("INGEST_AUTO_APPROVE", raising=False)
    graph, cfg = _start("t-reject")
    graph.invoke(Command(resume="reject"), cfg)
    snap = graph.get_state(cfg)
    assert snap.next == ()
    assert indexed == []
    assert snap.values["stats"]["approved"] is False


def test_auto_approve_does_not_pause(monkeypatch, indexed):
    monkeypatch.setenv("INGEST_AUTO_APPROVE", "1")
    graph, cfg = _start("t-auto")
    snap = graph.get_state(cfg)
    assert snap.next == ()
    assert indexed == [2]
    assert snap.values["stats"]["approved_by"] == "auto"


def test_nothing_pending_does_not_page_a_human(monkeypatch, indexed):
    monkeypatch.delenv("INGEST_AUTO_APPROVE", raising=False)
    monkeypatch.setattr(g, "_n_quality", lambda s: {"accepted": []})
    graph, cfg = _start("t-empty")
    assert graph.get_state(cfg).next == ()


def test_sqlite_checkpointer_survives_a_new_graph(monkeypatch, indexed, tmp_path):
    """Pause in one compiled graph, resume from a fresh one on the same SQLite file —
    what `python -m ingestion.run --resume` does in a new process."""
    monkeypatch.delenv("INGEST_AUTO_APPROVE", raising=False)
    monkeypatch.setattr(g.config, "STATE_DIR", tmp_path)
    cfg = {"configurable": {"thread_id": "t-sqlite"}}
    g.build_graph().invoke({"run_id": "t-sqlite", "rejects": [], "stats": {}}, cfg)
    assert (tmp_path / "checkpoints.sqlite").exists()
    fresh = g.build_graph()
    assert fresh.get_state(cfg).next == ("gate",)
    fresh.invoke(Command(resume="approve"), cfg)
    assert indexed == [2]

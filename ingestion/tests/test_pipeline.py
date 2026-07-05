"""Offline unit tests for the ingestion pipeline — no network, no LLM, no Qdrant.

Covers the pure-logic stages that must stay correct as the pipeline evolves: the quality
gate (dedup / relevance / IP-leak quarantine), the formula heuristic, chunk windowing,
and the storage round-trip. Fast enough to run on every CI push.
"""

from __future__ import annotations

import hashlib

from ingestion.enrich import _windows
from ingestion.parse import _looks_like_formula
from ingestion.quality import quality_gate
from ingestion.state import Chunk
from ingestion.storage import LocalStorage


def _chunk(text: str, cid: int = 0, doc: str = "d1") -> Chunk:
    return Chunk(
        id=cid, doc_id=doc, title="t", source_url="u", text=text,
        sha256=hashlib.sha256(text.encode()).hexdigest(),
    )


def test_quality_gate_dedups_identical_chunks():
    body = "Mean reversion is a tendency for prices to return toward a long-run average over time."
    accepted, rejects = quality_gate([_chunk(body, 0), _chunk(body, 1)])
    assert len(accepted) == 1
    assert any(r.reason == "duplicate" for r in rejects)


def test_quality_gate_drops_low_relevance():
    accepted, rejects = quality_gate([_chunk("12 34 56"), _chunk("[1] [2] [3] 4 5 6 7 8 9 0 1 2")])
    assert accepted == []
    assert all(r.reason == "low-relevance" for r in rejects)


def test_quality_gate_quarantines_ip_leak():
    # Names a proprietary strategy AND discloses concrete params -> quarantined.
    leak = ("The nifty-expiry strategy enters when z_entry exceeds 2.5 with a stop_pct of "
            "1.5 percent on a lookback of 50 bars, which is the proprietary edge.")
    accepted, rejects = quality_gate([_chunk(leak)])
    assert accepted == []
    assert rejects and rejects[0].reason == "ip-leak-quarantine"


def test_quality_gate_allows_generic_methodology():
    ok = ("Walk-forward validation repeatedly fits parameters on a past window and tests on "
          "the next, respecting the arrow of time to reduce overfitting in backtests.")
    accepted, rejects = quality_gate([_chunk(ok)])
    assert len(accepted) == 1 and rejects == []


def test_formula_heuristic_flags_math_lines():
    assert _looks_like_formula("σ = √(Σ (x_i − μ)² / n)") is True
    assert _looks_like_formula("We estimate the volatility of the returns series.") is False


def test_windows_overlap_and_cover():
    words = " ".join(f"w{i}" for i in range(1000))
    chunks = _windows(words)
    assert len(chunks) >= 2
    # every original word appears in at least one window
    joined = " ".join(chunks).split()
    assert "w0" in joined and "w999" in joined


def test_local_storage_roundtrip(tmp_path):
    st = LocalStorage(tmp_path)
    assert st.exists("raw/x.pdf") is False
    st.put_bytes("raw/x.pdf", b"%PDF-1.7 hello")
    assert st.exists("raw/x.pdf") is True
    assert st.get_bytes("raw/x.pdf") == b"%PDF-1.7 hello"
    assert st.uri("raw/x.pdf").startswith("file://")

"""Offline unit tests for the ingestion pipeline — no network, no LLM, no Qdrant.

Covers the pure-logic stages that must stay correct as the pipeline evolves: the quality
gate (dedup / relevance / IP-leak quarantine), the formula heuristic, chunk windowing,
and the storage round-trip. Fast enough to run on every CI push.
"""

from __future__ import annotations

import hashlib

import pytest

from ingestion.enrich import _windows, enrich
from ingestion.parse import _looks_like_formula
from ingestion.quality import quality_gate
from ingestion.state import Chunk, FetchedDoc, SourceDoc
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


# --- sub-project A: figures / vision captioning (needs PyMuPDF + Pillow) -------------

def _synthetic_pdf(path) -> None:
    """A one-page PDF with an inked region above a 'Figure 1:' caption."""
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=400, height=600)
    page.draw_rect(fitz.Rect(80, 120, 320, 300), color=(0, 0, 0), fill=(0.2, 0.4, 0.8))
    page.insert_text((80, 340), "Figure 1: A synthetic test chart of returns.", fontsize=11)
    page.insert_text((80, 380), "Body prose describing the methodology in some detail here.", fontsize=11)
    doc.save(str(path))
    doc.close()


def _fetched_for(pdf_path) -> FetchedDoc:
    return FetchedDoc(
        source=SourceDoc(id="test.0001", title="A Test Paper", pdf_url="http://x/pdf"),
        local_path=str(pdf_path), sha256="deadbeef" * 8, n_bytes=1,
    )


def test_render_figures_finds_caption_anchored_band(tmp_path, monkeypatch):
    pytest.importorskip("fitz")
    pytest.importorskip("PIL")
    from ingestion import config
    from ingestion.figures import render_figures

    monkeypatch.setattr(config, "PUBLIC_FIGURES_DIR", tmp_path / "figs")
    pdf = tmp_path / "p.pdf"
    _synthetic_pdf(pdf)

    figs = render_figures(_fetched_for(pdf), LocalStorage(tmp_path / "store"), max_per_doc=4)
    assert len(figs) >= 1
    f = figs[0]
    assert f.caption_text.lower().startswith("figure 1")
    assert f.image_bytes and f.vision_bytes           # full-res + down-scaled copy
    assert (tmp_path / "figs").glob("*.jpg")           # a public thumbnail was written
    assert f.thumb_rel.startswith("/data/figures/")


def test_caption_falls_back_to_printed_caption_without_api_key(tmp_path, monkeypatch):
    pytest.importorskip("fitz")
    pytest.importorskip("PIL")
    from ingestion import config
    from ingestion.caption import caption_figures
    from ingestion.parse import parse_pdf

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(config, "PUBLIC_FIGURES_DIR", tmp_path / "figs")
    pdf = tmp_path / "p.pdf"
    _synthetic_pdf(pdf)
    storage = LocalStorage(tmp_path / "store")
    fetched = _fetched_for(pdf)

    parsed = parse_pdf(fetched, storage)
    docs, spent, n = caption_figures([parsed], [fetched], storage, start_spent=0.0)
    assert n >= 1 and spent == 0.0                      # no LLM spend without a key
    img_blocks = [b for b in docs[0].blocks if b.kind == "image" and b.text]
    assert img_blocks and "figure 1" in img_blocks[0].text.lower()

    # …and enrich turns that captioned figure into an indexable image chunk
    chunks, _ = enrich(docs, start_spent=0.0)
    fig_chunks = [c for c in chunks if c.kind == "image"]
    assert fig_chunks and fig_chunks[0].image_path

"""WP12 layout router: free labels, three backends behind one protocol, and a DAG node that
changes nothing downstream in the default ``rules`` mode. Offline: no key, no Ollama."""

from __future__ import annotations

import json

import pytest

from ingestion.layout_labels import (
    LABELS,
    PageFeatures,
    derive_label,
    feature_string,
    page_features,
    synthetic_pages,
)
from ingestion.layout_router import (
    LayoutClassifier,
    LayoutVerdict,
    RulesClassifier,
    get_classifier,
    route_pages,
    slm_classifier,
    vision_pages,
)
from ingestion.state import Block, ParsedDoc


def _f(**kw) -> PageFeatures:
    base = {"doc_id": "d", "page": 1, "n_chars": 3000, "n_lines": 50, "mean_line_len": 60.0,
            "n_table_blocks": 0, "table_chars": 0, "n_images": 0, "image_px_share": 0.0,
            "n_figure_captions": 0}
    base.update(kw)
    return PageFeatures(**base)


# --- the teacher rule ------------------------------------------------------------------

@pytest.mark.parametrize("kw,label", [
    ({"n_chars": 40}, "scanned"),
    ({}, "text"),
    ({"n_table_blocks": 1, "table_chars": 1500}, "table-heavy"),
    ({"n_table_blocks": 1, "table_chars": 300}, "mixed"),
    ({"n_chars": 900, "n_figure_captions": 1}, "figure-heavy"),
    ({"n_figure_captions": 1}, "mixed"),
    ({"n_table_blocks": 1, "table_chars": 2500, "n_images": 1}, "mixed"),
])
def test_derive_label_rule(kw, label):
    assert derive_label(_f(**kw)) == label


def test_page_features_from_parsed_doc():
    doc = ParsedDoc(source_id="x", title="t", pdf_url="u", pages_processed=3, blocks=[
        Block(kind="text", text="Some prose line\nFigure 1: A chart", page=1),
        Block(kind="table", text="a | b\n1 | 2", page=2),
        Block(kind="text", text="cells", page=2),
        Block(kind="image", page=1, meta={"w": 1275, "h": 825}),
        Block(kind="image", page=1, text="captioned", meta={"thumb": "/data/x.jpg"}),
    ])
    pages = page_features(doc)
    assert [p.page for p in pages] == [1, 2, 3]            # empty page 3 still gets a record
    p1, p2, p3 = pages
    assert p1.n_figure_captions == 1 and p1.n_images == 1 and p1.image_px_share == 0.5
    assert p2.n_table_blocks == 1 and p2.table_chars == len("a | b\n1 | 2")
    assert p3.n_chars == 0 and derive_label(p3) == "scanned"
    assert "figure_captions=1" in feature_string(p1)


def test_synthetic_pages_are_deterministic_and_cover_every_class():
    a, b = synthetic_pages(), synthetic_pages()
    assert a == b and len(a) == 200
    assert {derive_label(p) for p in a} == set(LABELS)


# --- backends ----------------------------------------------------------------------------

def test_default_backend_is_rules(monkeypatch):
    monkeypatch.delenv("YANTRA_LAYOUT_BACKEND", raising=False)
    clf = get_classifier()
    assert isinstance(clf, RulesClassifier) and isinstance(clf, LayoutClassifier)
    with pytest.raises(ValueError):
        get_classifier("gpu-cluster")


def test_rules_backend_emits_valid_labels_and_flags():
    recs = route_pages(synthetic_pages(60), RulesClassifier())
    assert all(r["label"] in LABELS and r["backend"] == "rules" for r in recs)
    for r in recs:
        assert r["needs_ocr"] == (r["label"] == "scanned")
        assert r["needs_vision"] == (r["label"] == "figure-heavy")


def test_slm_backend_through_fake_provider_with_strict_schema():
    from llm_gateway import FakeProvider

    fake = FakeProvider([
        '{"label": "chart", "confidence": 0.9}',            # not a label → one repair
        LayoutVerdict(label="figure-heavy", confidence=0.8),
    ], name="ollama", model="qwen2.5:1.5b")
    d = slm_classifier(fake).classify(_f(n_chars=900, n_figure_captions=1))
    assert (d.label, d.backend, d.cost_usd) == ("figure-heavy", "slm", 0.0)
    assert fake.calls[0]["schema"] is LayoutVerdict
    assert "figure_captions=1" in fake.calls[0]["messages"][0]["content"]
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        LayoutVerdict.model_validate({"label": "text", "confidence": 0.5, "why": "x"})


def test_slm_backend_fails_clearly_when_ollama_is_down(monkeypatch):
    from llm_gateway.base import ProviderUnavailable
    from llm_gateway.ollama_provider import OllamaProvider

    clf = slm_classifier(OllamaProvider(model="qwen2.5:1.5b", host="http://127.0.0.1:9"))
    with pytest.raises(ProviderUnavailable, match="Ollama server unreachable"):
        clf.classify(_f())                                 # no silent fallback to rules


def test_vision_pages_from_layout_records():
    layout = [{"doc_id": "a", "page": 1, "needs_vision": True},
              {"doc_id": "a", "page": 2, "needs_vision": False},
              {"doc_id": "b", "page": 1, "needs_vision": False}]
    assert vision_pages(layout) == {"a": {1}, "b": set()}


# --- the DAG node: rules mode changes nothing downstream --------------------------------

def _layout_pdf(path) -> None:
    """Four pages: prose, a ruled table, a figure with a caption, and a blank page."""
    import fitz

    doc = fitz.open()
    p = doc.new_page(width=400, height=600)
    prose = ("Walk-forward validation refits the model on a rolling window and tests on the "
             "next one, which respects the arrow of time. ")
    y = 60
    for _ in range(12):
        p.insert_textbox(fitz.Rect(40, y, 360, y + 40), prose, fontsize=8)
        y += 42
    p = doc.new_page(width=400, height=600)
    p.insert_text((40, 60), "Table 1: Out-of-sample results", fontsize=10)
    for r in range(6):
        for c in range(4):
            cell = fitz.Rect(40 + c * 80, 80 + r * 24, 120 + c * 80, 104 + r * 24)
            p.draw_rect(cell, color=(0, 0, 0), width=0.8)
            p.insert_text((cell.x0 + 6, cell.y0 + 16), f"{r * 4 + c}.{r}", fontsize=9)
    p = doc.new_page(width=400, height=600)
    p.draw_rect(fitz.Rect(80, 120, 320, 300), color=(0, 0, 0), fill=(0.2, 0.4, 0.8))
    p.insert_text((80, 340), "Figure 1: A synthetic test chart of returns.", fontsize=11)
    p.insert_text((80, 380), "Body prose describing the methodology in some detail here.",
                  fontsize=11)
    doc.new_page(width=400, height=600)
    doc.save(str(path))
    doc.close()


def _run_dag(tmp_path, monkeypatch, layout_node) -> dict:
    from langgraph.checkpoint.memory import InMemorySaver

    from ingestion import config
    from ingestion import graph as g
    from ingestion.state import FetchedDoc, SourceDoc

    pdf = tmp_path / "doc.pdf"
    if not pdf.exists():
        _layout_pdf(pdf)
    fetched = FetchedDoc(source=SourceDoc(id="test.0002", title="Layout Paper", pdf_url="u"),
                         local_path=str(pdf), sha256="ab" * 32, n_bytes=1)
    monkeypatch.setattr(config, "PUBLIC_FIGURES_DIR", tmp_path / "figs")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(g, "_n_discover", lambda s: {"sources": [], "rejects": []})
    monkeypatch.setattr(g, "_n_fetch", lambda s: {"fetched": [fetched.model_dump()]})
    monkeypatch.setattr(g, "_n_index", lambda s: {"indexed": len(s["accepted"])})
    monkeypatch.setattr(g, "_n_layout", layout_node)
    graph = g.build_graph(InMemorySaver())
    cfg = {"configurable": {"thread_id": "t"}}
    graph.invoke({"run_id": "t", "rejects": [], "spent_usd": 0.0, "stats": {}}, cfg)
    return graph.get_state(cfg).values


def test_dag_output_is_byte_identical_with_the_rules_router(tmp_path, monkeypatch):
    pytest.importorskip("fitz")
    pytest.importorskip("PIL")
    pytest.importorskip("langgraph")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("S3_BUCKET", raising=False)
    monkeypatch.delenv("YANTRA_LAYOUT_BACKEND", raising=False)
    monkeypatch.delenv("INGEST_LAYOUT_GATE_CAPTION", raising=False)
    monkeypatch.setenv("INGEST_AUTO_APPROVE", "1")

    from ingestion import graph as g

    router = g._n_layout
    before = _run_dag(tmp_path, monkeypatch, layout_node=lambda s: {})   # the DAG as it was
    after = _run_dag(tmp_path, monkeypatch, layout_node=router)         # with the router
    for key in ("parsed", "chunks", "accepted", "rejects", "indexed", "spent_usd", "stats"):
        assert json.dumps(before.get(key), sort_keys=True) == json.dumps(after.get(key), sort_keys=True), key
    assert "layout" not in before

    labels = {r["page"]: r["label"] for r in after["layout"]}
    assert labels == {1: "text", 2: "table-heavy", 3: "figure-heavy", 4: "scanned"}
    # routing flags match what the pipeline already does: the blank page is the one parse
    # would send to OCR (< 20 chars), and the caption-anchored page is the figure page
    flags = {r["page"]: (r["needs_ocr"], r["needs_vision"]) for r in after["layout"]}
    assert flags == {1: (False, False), 2: (False, False), 3: (False, True), 4: (True, False)}


def test_gate_caption_limits_vision_to_marked_pages(tmp_path, monkeypatch):
    pytest.importorskip("fitz")
    pytest.importorskip("PIL")
    from ingestion import config
    from ingestion.figures import render_figures
    from ingestion.state import FetchedDoc, SourceDoc
    from ingestion.storage import LocalStorage

    monkeypatch.setattr(config, "PUBLIC_FIGURES_DIR", tmp_path / "figs")
    pdf = tmp_path / "doc.pdf"
    _layout_pdf(pdf)
    fd = FetchedDoc(source=SourceDoc(id="t.3", title="t", pdf_url="u"), local_path=str(pdf),
                    sha256="cd" * 32, n_bytes=1)
    st = LocalStorage(tmp_path / "store")
    assert len(render_figures(fd, st, max_per_doc=4)) >= 1          # default: every page
    assert render_figures(fd, st, max_per_doc=4, pages=set()) == []  # nothing marked
    assert [f.page for f in render_figures(fd, st, max_per_doc=4, pages={3})] == [3]


def test_layout_eval_harness_runs_offline(tmp_path, capsys):
    from eval.layout_eval import FAKE_BANNER, main

    out = tmp_path / "layout.md"
    assert main(["--fake", "--dataset", "synthetic", "--out", str(out)]) == 0
    text = out.read_text(encoding="utf-8")
    assert FAKE_BANNER in text
    rows = [ln for ln in text.splitlines() if ln.startswith("| ") and "backend" not in ln]
    assert [r.split("|")[1].strip() for r in rows] == ["rules", "slm", "frontier"]
    assert "| rules | thresholds (code) | 0.90 |" in text      # deterministic: synthetic seed 2026

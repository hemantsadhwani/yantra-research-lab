"""Page-level layout router: code, then a small model, then a frontier model, behind one protocol.

Every parsed page gets one of five labels (``text``, ``table-heavy``, ``figure-heavy``,
``scanned``, ``mixed``) and a routing decision: ``scanned`` pages are marked for OCR,
``figure-heavy`` pages for vision captioning, everything else skips the expensive step.

Three backends implement ``LayoutClassifier``, chosen by ``YANTRA_LAYOUT_BACKEND``:

* ``rules``    (default, offline, $0): thresholds over the cheap counts in ``PageFeatures``.
* ``slm``      a local model through the ``llm_gateway`` Ollama provider (``qwen2.5:1.5b``
               unless ``OLLAMA_MODEL`` is set). If Ollama is not reachable it raises
               ``ProviderUnavailable``: there is no silent fallback to ``rules``, because a
               router that quietly changes tier would make its own eval meaningless.
* ``frontier`` Claude Haiku 4.5 through the gateway (``YANTRA_LAYOUT_FRONTIER_PROVIDER``,
               default ``anthropic``; ``bedrock`` also works). Costs money; never run in CI.

Both model backends use the same strict schema (``LayoutVerdict``) and the same prompt: the
feature line from ``layout_labels.feature_string`` plus the first 400 characters of text.
The rules backend deliberately reads the coarse counts only (table *blocks*, line length,
figure anchors), not the content shares the teacher rule in ``layout_labels`` uses, so its
score against those labels is a measurement, not an identity.

The router is advisory by default: the DAG records ``layout`` per page and changes nothing
else. ``INGEST_LAYOUT_GATE_CAPTION=1`` makes the caption step honour the routing decision
(only pages marked for vision are rasterized and captioned).
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from ingestion.layout_labels import LABELS, PageFeatures, feature_string

LayoutLabel = Literal["text", "table-heavy", "figure-heavy", "scanned", "mixed"]
BACKENDS = ("rules", "slm", "frontier")
DEFAULT_SLM_MODEL = "qwen2.5:1.5b"
FRONTIER_MODEL = "claude-haiku-4-5"
MAX_TOKENS = 60


class LayoutVerdict(BaseModel):
    """The only shape a model backend may return."""

    model_config = ConfigDict(extra="forbid")
    label: LayoutLabel
    confidence: float = Field(ge=0.0, le=1.0)


@dataclass(frozen=True)
class LayoutDecision:
    label: str
    confidence: float
    backend: str
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def needs_ocr(self) -> bool:
        return self.label == "scanned"

    @property
    def needs_vision(self) -> bool:
        return self.label == "figure-heavy"


@runtime_checkable
class LayoutClassifier(Protocol):
    name: str

    def classify(self, f: PageFeatures) -> LayoutDecision: ...


# --- tier 1: code ------------------------------------------------------------------------

class RulesClassifier:
    """Thresholds over counts. No content shares, no model, no network."""

    name = "rules"

    def classify(self, f: PageFeatures) -> LayoutDecision:
        if f.n_chars < 100:
            return LayoutDecision("scanned", 0.9, self.name)
        has_table = f.n_table_blocks > 0
        has_fig = f.n_figure_captions > 0 or f.n_images > 0 or f.image_px_share >= 0.3
        if has_table and has_fig:
            return LayoutDecision("mixed", 0.7, self.name)
        if has_table:
            # short lines = the page is mostly cells, not prose
            return (LayoutDecision("table-heavy", 0.7, self.name) if f.mean_line_len < 40
                    else LayoutDecision("mixed", 0.6, self.name))
        if has_fig:
            return (LayoutDecision("figure-heavy", 0.7, self.name) if f.n_chars < 1500
                    else LayoutDecision("mixed", 0.6, self.name))
        return LayoutDecision("text", 0.8, self.name)


# --- tiers 2 and 3: a model through llm_gateway ----------------------------------------

SYSTEM = (
    "You classify one page of a research PDF by layout, from parser features and a text "
    "snippet. Classes:\n"
    "- text: mostly prose.\n"
    "- table-heavy: tables make up a large share of the page.\n"
    "- figure-heavy: a figure (chart, plot, image) fills much of the page; little prose.\n"
    "- scanned: little or no extractable text (an image of a page).\n"
    "- mixed: prose plus a smaller table or figure, or both a table and a figure.\n"
    "Reply with the label and your confidence from 0 to 1."
)


def build_messages(f: PageFeatures) -> list[dict]:
    snippet = f.snippet[:400] or "(no text)"
    return [{"role": "user", "content": f"Features: {feature_string(f)}\nText:\n{snippet}"}]


class ModelClassifier:
    """A gateway ``Provider`` asked for a ``LayoutVerdict``. Errors propagate: no fallback."""

    def __init__(self, provider, name: str) -> None:
        self.provider = provider
        self.name = name

    def classify(self, f: PageFeatures) -> LayoutDecision:
        resp = self.provider.complete(system=SYSTEM, messages=build_messages(f),
                                      max_tokens=MAX_TOKENS, schema=LayoutVerdict)
        v: LayoutVerdict = resp.parsed
        return LayoutDecision(v.label, v.confidence, self.name, resp.cost_usd,
                              resp.input_tokens, resp.output_tokens)


def slm_classifier(provider=None) -> ModelClassifier:
    if provider is None:
        from llm_gateway import get_provider
        provider = get_provider("ollama", model=os.environ.get("OLLAMA_MODEL") or DEFAULT_SLM_MODEL)
    return ModelClassifier(provider, "slm")


def frontier_classifier(provider=None) -> ModelClassifier:
    if provider is None:
        from llm_gateway import get_provider
        name = os.environ.get("YANTRA_LAYOUT_FRONTIER_PROVIDER", "anthropic")
        provider = get_provider(name, model=FRONTIER_MODEL if name == "anthropic" else None)
    return ModelClassifier(provider, "frontier")


def get_classifier(backend: str | None = None, provider=None) -> LayoutClassifier:
    chosen = (backend or os.environ.get("YANTRA_LAYOUT_BACKEND") or "rules").strip().lower()
    if chosen == "rules":
        return RulesClassifier()
    if chosen == "slm":
        return slm_classifier(provider)
    if chosen == "frontier":
        return frontier_classifier(provider)
    raise ValueError(f"unknown layout backend {chosen!r}; valid: {', '.join(BACKENDS)}")


def route_pages(pages: list[PageFeatures], clf: LayoutClassifier) -> list[dict]:
    """Classify every page; one JSON-safe record per page for the pipeline state."""
    out = []
    for f in pages:
        t0 = time.perf_counter()
        d = clf.classify(f)
        assert d.label in LABELS, d.label
        out.append({"doc_id": f.doc_id, "page": f.page, "label": d.label,
                    "confidence": round(d.confidence, 3), "backend": d.backend,
                    "needs_ocr": d.needs_ocr, "needs_vision": d.needs_vision,
                    "latency_ms": round((time.perf_counter() - t0) * 1000, 3)})
    return out


def gate_caption() -> bool:
    return os.environ.get("INGEST_LAYOUT_GATE_CAPTION", "0").strip() == "1"


def vision_pages(layout: list[dict]) -> dict[str, set[int]]:
    """``{doc_id: {pages marked for vision}}`` from the ``layout`` state records."""
    out: dict[str, set[int]] = {}
    for r in layout:
        out.setdefault(r["doc_id"], set())
        if r["needs_vision"]:
            out[r["doc_id"]].add(r["page"])
    return out

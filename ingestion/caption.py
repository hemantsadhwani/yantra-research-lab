"""Stage 3b — Caption (agentic vision, sub-project A).

Turns the figures found by ``figures.render_figures`` into indexable, retrievable units:
each rasterized band is described by one bounded Claude vision call, and the resulting
caption is attached to the doc as an ``image`` block (with its S3 path + public thumbnail).
Downstream, ``enrich`` embeds those captions, giving **caption-based multimodal retrieval**
— a text query like "drawdown curve" can surface the right figure.

Bounded autonomy, same as enrich: a hard per-run USD budget and hard figure caps (per-doc
and per-run) keep this near-zero. The figure's own printed caption is always the fallback,
so figures still index even with vision disabled or the budget exhausted.
"""

from __future__ import annotations

import hashlib

from ingestion import config
from ingestion.figures import render_figures, reset_public_figures
from ingestion.llm import caption_image
from ingestion.state import Block, FetchedDoc, ParsedDoc

_VISION_SYSTEM = (
    "You caption figures from quant-finance research papers for a retrieval index. "
    "In 2-3 factual sentences describe: what the figure shows, its chart type, the axes/"
    "variables, and the key takeaway. No preamble, no markdown, no guessing beyond the image."
)


def _caption_one(fig, title: str, spent: float) -> tuple[str, float, bool]:
    """Return (caption_text, cost, used_vision). Falls back to the printed caption."""
    fallback = fig.caption_text or "Figure (no caption text extracted)."
    if not config.CAPTION_FIGURES or spent >= config.TOKEN_BUDGET_USD:
        return fallback, 0.0, False
    user = (f"Paper: {title}\nPrinted caption: {fig.caption_text or '(none)'}\n"
            "Describe this figure for search.")
    text, cost = caption_image(
        _VISION_SYSTEM, user, fig.vision_bytes, fig.vision_media_type,
        model=config.VISION_MODEL, max_tokens=config.VISION_MAX_TOKENS,
    )
    if not text:
        return fallback, cost, False
    # Keep the printed caption too — it carries the figure number + author's own words.
    combined = f"{fig.caption_text} — {text}" if fig.caption_text else text
    return combined[:900], cost, True


def caption_figures(
    parsed_docs: list[ParsedDoc], fetched: list[FetchedDoc], storage,
    start_spent: float = 0.0,
) -> tuple[list[ParsedDoc], float, int]:
    """Render + caption figures, appending image blocks to each doc.

    Returns (parsed_docs, total_spent_usd, n_captioned_total).
    """
    reset_public_figures()
    by_id = {f.source.id: f for f in fetched}
    spent = start_spent
    total_captioned = 0

    for doc in parsed_docs:
        fd = by_id.get(doc.source_id)
        if fd is None or total_captioned >= config.MAX_FIGURES_TOTAL:
            continue
        remaining = min(config.MAX_FIGURES_PER_DOC, config.MAX_FIGURES_TOTAL - total_captioned)
        if remaining <= 0:
            continue
        try:
            figs = render_figures(fd, storage, max_per_doc=remaining)
        except Exception:
            continue

        n_doc = 0
        for fig in figs:
            caption, cost, used_vision = _caption_one(fig, doc.title, spent)
            spent += cost
            doc.blocks.append(Block(
                kind="image", text=caption, page=fig.page,
                image_path=fig.storage_uri or fig.thumb_rel,
                meta={"thumb": fig.thumb_rel, "caption_text": fig.caption_text,
                      "vision": used_vision, "w": fig.meta.get("w"), "h": fig.meta.get("h")},
            ))
            n_doc += 1
            total_captioned += 1
            if total_captioned >= config.MAX_FIGURES_TOTAL:
                break
        doc.n_captioned = n_doc

    return parsed_docs, spent, total_captioned


def figure_chunk_sha(doc_id: str, page: int, caption: str) -> str:
    """Stable dedup/id key for a figure chunk (distinct from text-chunk hashing)."""
    return hashlib.sha256(f"fig::{doc_id}::{page}::{caption}".encode("utf-8")).hexdigest()

"""Page features and free layout labels, derived from the parser's own output (silver layer).

Two things live here, both stdlib-only and deterministic:

* ``page_features(parsed)`` turns one ``ParsedDoc`` into one ``PageFeatures`` record per
  processed page: character and line counts, table blocks and their share of the page
  text, embedded images, and "Figure N" caption anchors. These are the inputs every
  layout backend sees (``ingestion/layout_router.py``).
* ``derive_label(features)`` is the **teacher** for the layout kata. It reads the parsed
  structure (tables found by PyMuPDF's geometry pass, embedded images, figure captions)
  and names one of five classes with a fixed, documented rule. The labels cost nothing,
  because the parser already did the expensive work. The designed-but-not-run alternative
  is a frontier model as teacher (see ``docs/adr/0012-slm-cascade.md``).

The label rule, in order (first match wins):

1. ``scanned``       fewer than ``SCANNED_MAX_CHARS`` extractable characters on the page.
2. ``mixed``         at least one table block AND at least one figure signal.
3. ``table-heavy``   a table block, and table text is >= ``TABLE_HEAVY_SHARE`` of page text.
   ``mixed``         a table block below that share (a small table inside prose).
4. ``figure-heavy``  a figure signal, and the page has < ``FIGURE_HEAVY_MAX_CHARS`` characters
                     (the figure, not prose, fills the page).
   ``mixed``         a figure signal on a page with more prose than that.
5. ``text``          everything else.

A *figure signal* is an embedded raster image (>= 100 px, as ``parse.py`` keeps them) or a
printed "Figure N" caption line (vector plots have no embedded image; the caption is the
anchor ``figures.py`` already relies on).

Honest limits of this teacher: ``parse.py`` only scans the first ``TABLE_SCAN_MAX_PAGES``
pages for tables, so later tables are invisible to it; a page that ``parse.py`` OCR'd carries
OCR text and no per-page flag, so it reads as ``text``, not ``scanned``; the caption regex
(the one ``figures.py`` uses) runs per line, so a prose line that happens to begin
"Figure 3 shows" counts as a figure signal. The labels are
"what the parser saw", not human annotation.
"""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass

from ingestion.figures import _CAPTION_RE
from ingestion.state import ParsedDoc

LABELS: tuple[str, ...] = ("text", "table-heavy", "figure-heavy", "scanned", "mixed")

SCANNED_MAX_CHARS = 100          # below this, the page has "little or no extractable text"
TABLE_HEAVY_SHARE = 0.30         # table text / page text at or above which tables dominate
FIGURE_HEAVY_MAX_CHARS = 1800    # a full prose page in the corpus runs ~3,000-4,500 chars
# image_px_share is a proxy: the silver layer records image pixel size, not placement, so the
# share is pixels over a US-letter page rendered at 150 dpi (1275 x 1650), capped at 1.
_REF_PAGE_PX = 1275 * 1650
SNIPPET_CHARS = 400


@dataclass(frozen=True)
class PageFeatures:
    """Cheap per-page features. Everything here is already in the ParsedDoc."""

    doc_id: str
    page: int                    # 1-based
    n_chars: int                 # extractable text + formula characters
    n_lines: int                 # non-empty text + formula lines
    mean_line_len: float         # n_chars / n_lines (short lines: table cells, axis labels)
    n_table_blocks: int
    table_chars: int
    n_images: int                # embedded raster images kept by parse.py
    image_px_share: float        # proxy, see _REF_PAGE_PX
    n_figure_captions: int       # "Figure N" / "Fig. N" anchor lines
    snippet: str = ""            # first SNIPPET_CHARS characters of the page text

    @property
    def table_share(self) -> float:
        return min(1.0, self.table_chars / max(self.n_chars, 1))

    @property
    def figure_signal(self) -> int:
        return self.n_images + self.n_figure_captions

    def to_dict(self) -> dict:
        return asdict(self)


def feature_string(f: PageFeatures) -> str:
    """The canonical one-line feature rendering every model backend (and the LoRA) sees."""
    return (f"chars={f.n_chars} lines={f.n_lines} mean_line={f.mean_line_len:.1f} "
            f"tables={f.n_table_blocks} table_share={f.table_share:.2f} "
            f"images={f.n_images} image_share={f.image_px_share:.2f} "
            f"figure_captions={f.n_figure_captions}")


def page_features(parsed: ParsedDoc) -> list[PageFeatures]:
    """One record per processed page (pages with no blocks at all are included)."""
    n_pages = parsed.pages_processed or max((b.page for b in parsed.blocks), default=0)
    acc: dict[int, dict] = {
        p: {"chars": 0, "lines": 0, "tables": 0, "table_chars": 0, "images": 0,
            "px": 0, "captions": 0, "text": []}
        for p in range(1, n_pages + 1)
    }
    for b in parsed.blocks:
        a = acc.get(b.page)
        if a is None:
            continue
        if b.kind in ("text", "formula"):
            lines = [ln for ln in b.text.splitlines() if ln.strip()]
            a["chars"] += len(b.text)
            a["lines"] += len(lines)
            a["captions"] += sum(1 for ln in lines if _CAPTION_RE.match(ln.strip()))
            if b.kind == "text":
                a["text"].append(b.text)
        elif b.kind == "table":
            a["tables"] += 1
            a["table_chars"] += len(b.text)
        elif b.kind == "image" and not (b.meta or {}).get("thumb"):
            # parse.py image blocks only; captioned figures (meta.thumb) come later in the DAG
            a["images"] += 1
            a["px"] += int((b.meta or {}).get("w") or 0) * int((b.meta or {}).get("h") or 0)
    out = []
    for p, a in acc.items():
        out.append(PageFeatures(
            doc_id=parsed.source_id, page=p, n_chars=a["chars"], n_lines=a["lines"],
            mean_line_len=round(a["chars"] / a["lines"], 1) if a["lines"] else 0.0,
            n_table_blocks=a["tables"], table_chars=a["table_chars"], n_images=a["images"],
            image_px_share=round(min(1.0, a["px"] / _REF_PAGE_PX), 3),
            n_figure_captions=a["captions"],
            snippet="\n".join(a["text"])[:SNIPPET_CHARS],
        ))
    return out


def derive_label(f: PageFeatures) -> str:
    """The deterministic teacher rule (see the module docstring)."""
    if f.n_chars < SCANNED_MAX_CHARS:
        return "scanned"
    has_table, has_fig = f.n_table_blocks > 0, f.figure_signal > 0
    if has_table and has_fig:
        return "mixed"
    if has_table:
        return "table-heavy" if f.table_share >= TABLE_HEAVY_SHARE else "mixed"
    if has_fig:
        return "figure-heavy" if f.n_chars < FIGURE_HEAVY_MAX_CHARS else "mixed"
    return "text"


# --- deterministic synthetic pages (used when fewer than 40 real parsed pages exist) -----

_SNIPPETS = {
    "text": "We estimate the drift of the latent process by filtering the observed returns. ",
    "table-heavy": "Table 2: Out-of-sample Sharpe by window\n0.81 | 0.77 | 0.64\n1.02 | 0.95 | 0.88\n",
    "figure-heavy": "Figure 3: Cumulative wealth of the strategy\n0.0\n0.5\n1.0\n2019 2020 2021\n",
    "scanned": "",
    "mixed": "The table below and Figure 1 summarise the drawdown profile of each portfolio. ",
}


def synthetic_pages(n: int = 200, seed: int = 2026) -> list[PageFeatures]:
    """``n`` plausible page-feature records, labelled by ``derive_label`` (so, rule-consistent).

    Each record is drawn around a target class with noise that crosses the thresholds on
    purpose, so the backends have boundary cases to get wrong. Same ``seed``, same pages.
    """
    rng = random.Random(seed)
    weights = {"text": 0.45, "mixed": 0.2, "table-heavy": 0.12, "figure-heavy": 0.15,
               "scanned": 0.08}
    classes = list(weights)
    out: list[PageFeatures] = []
    for i in range(n):
        target = rng.choices(classes, weights=[weights[c] for c in classes])[0]
        tables = images = captions = 0
        table_chars = 0
        if target == "scanned":
            chars = rng.randint(0, 140)
            images = rng.choice([0, 1, 1])
        elif target == "text":
            chars = rng.randint(1200, 4600)
        elif target == "table-heavy":
            chars = rng.randint(500, 3200)
            tables = rng.choice([1, 1, 2])
            table_chars = int(chars * rng.uniform(0.22, 0.9))
        elif target == "figure-heavy":
            chars = rng.randint(250, 2300)
            captions = 1
            images = rng.choice([0, 0, 1])
        else:  # mixed
            chars = rng.randint(1500, 4200)
            if rng.random() < 0.5:
                tables, table_chars = 1, int(chars * rng.uniform(0.05, 0.35))
            if tables == 0 or rng.random() < 0.4:
                captions = 1
        mean_line = rng.uniform(12, 30) if (tables or captions) else rng.uniform(45, 85)
        lines = max(1, int(chars / mean_line)) if chars else 0
        px = images * rng.randint(200_000, 1_600_000)
        f = PageFeatures(
            doc_id=f"synthetic-{i // 12:03d}", page=i % 12 + 1, n_chars=chars, n_lines=lines,
            mean_line_len=round(chars / lines, 1) if lines else 0.0, n_table_blocks=tables,
            table_chars=table_chars, n_images=images,
            image_px_share=round(min(1.0, px / _REF_PAGE_PX), 3), n_figure_captions=captions,
            snippet=_SNIPPETS[target][:SNIPPET_CHARS] if chars >= SCANNED_MAX_CHARS else "",
        )
        out.append(f)
    return out

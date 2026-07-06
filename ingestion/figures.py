"""Figure extraction (sub-project A) — find figures and rasterize them.

arXiv figures are usually *vector* drawings, so ``page.get_images()`` returns nothing.
Instead we anchor on the printed caption ("Figure 3: …") and rasterize the band directly
above it — bounded below by the caption and above by the nearest text block — which
brackets the figure regardless of whether it's raster or vector. Each rendered band is:

  - written full-resolution (PNG) to object storage (S3 bronze) for lineage, and
  - down-scaled to a small JPEG thumbnail under ``PUBLIC_FIGURES_DIR`` so the public site
    can show figures WITHOUT exposing the private bucket.

A light ink-fraction check drops blank bands (a caption with no figure above it). Counts
are capped per-doc and per-run to keep vision cost and committed thumbnails near-zero.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from typing import Optional

from ingestion import config
from ingestion.state import FetchedDoc
from ingestion.storage import Storage

# "Figure 3:", "Fig. 3.", "FIGURE 12 —" … the anchor that proves a figure exists.
_CAPTION_RE = re.compile(r"^\s*(figure|fig\.?)\s*\d+", re.IGNORECASE)


@dataclass
class Figure:
    """A rasterized figure region, before captioning."""
    doc_id: str
    page: int                       # 1-based
    index: int                      # nth figure in the doc
    caption_text: str               # the paper's own printed caption (fallback caption)
    image_bytes: bytes              # full-res PNG (→ S3 bronze)
    media_type: str = "image/png"
    vision_bytes: bytes = b""       # down-scaled copy sent to the vision model
    vision_media_type: str = "image/jpeg"
    storage_uri: str = ""           # s3://… once uploaded
    thumb_rel: str = ""             # /data/figures/… public path once written
    meta: dict = field(default_factory=dict)


def _resize_jpeg(png_bytes: bytes, max_px: int, quality: int) -> tuple[bytes, int, int]:
    """Down-scale a PNG to a JPEG with the long edge <= max_px. Returns (bytes, w, h)."""
    from PIL import Image

    im = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    w, h = im.size
    scale = min(1.0, max_px / max(w, h))
    if scale < 1.0:
        im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue(), im.size[0], im.size[1]


def _ink_fraction(png_bytes: bytes) -> float:
    """Fraction of non-near-white pixels — used to reject blank bands cheaply."""
    from PIL import Image

    im = Image.open(io.BytesIO(png_bytes)).convert("L").resize((64, 64))
    dark = sum(1 for p in im.getdata() if p < 240)
    return dark / 4096.0


def _geometry_rects(page):
    """Vector-drawing + embedded-image bounding boxes on the page, minus obvious noise.

    Plots are made of many vector paths; a figure's real extent is the union of those
    boxes (text-based 'nearest block above' fails because a plot's own axis/legend text
    sits right above the caption). Page frames and hairlines are filtered out.
    """
    import fitz

    pr = page.rect
    rects = []
    for d in page.get_drawings():
        r = d.get("rect")
        if r is not None:
            rects.append(fitz.Rect(r))
    try:
        for info in page.get_image_info(xrefs=True):
            bb = info.get("bbox")
            if bb:
                rects.append(fitz.Rect(bb))
    except Exception:
        pass
    out = []
    for r in rects:
        if r.width < 6 or r.height < 6:                       # hairline / dot
            continue
        if r.width > 0.97 * pr.width and r.height > 0.97 * pr.height:  # page frame
            continue
        out.append(r)
    return out


def _caption_clips(page):
    """Yield (clip_rect, caption_text) for each figure caption on the page.

    The figure region is the union of vector-drawing/image boxes (and in-band axis text)
    that sit within a bounded band above the caption. Falls back to a fixed band above the
    caption when a figure has no vector geometry (e.g. a purely rasterized page).
    """
    import fitz

    pr = page.rect
    ph = pr.height
    tblocks = [b for b in page.get_text("blocks") if len(b) >= 5 and (len(b) < 7 or b[6] == 0)]
    geom = _geometry_rects(page)

    for cb in tblocks:
        cx0, cy0, cx1, cy1, text = cb[0], cb[1], cb[2], cb[3], cb[4]
        if not _CAPTION_RE.match(text.strip()):
            continue
        lo = cy0 - config.FIGURE_MAX_BAND_FRAC * ph            # highest the figure may start
        # The figure's extent is defined by its own drawing/image geometry (a plot's axis
        # labels sit inside those boxes) — NOT by loose text above it, which would drag in
        # body paragraphs. Only vector/image boxes in the band above the caption count.
        cand = [r for r in geom if r.y1 <= cy0 + 2 and r.y1 >= lo]
        if cand:
            u = fitz.Rect(cand[0])
            for r in cand[1:]:
                u |= r
            top = max(u.y0, lo)
            x0, x1 = max(u.x0, pr.x0), min(u.x1, pr.x1)
        else:
            top = cy0 - config.FIGURE_FALLBACK_BAND_FRAC * ph  # no vector geometry → fixed band
            x0, x1 = pr.x0 + 0.05 * pr.width, pr.x1 - 0.05 * pr.width
        if cy0 - top < config.FIGURE_MIN_BAND_FRAC * ph:       # too thin to be a figure
            continue
        clip = fitz.Rect(min(x0, cx0), top, max(x1, cx1), cy0 - 1)
        yield clip, " ".join(text.split())[:400]


def render_figures(fetched: FetchedDoc, storage: Storage, max_per_doc: int) -> list[Figure]:
    """Detect + rasterize up to ``max_per_doc`` figures from a PDF. No LLM here."""
    import fitz

    figs: list[Figure] = []
    doc = fitz.open(fetched.local_path)
    src = fetched.source
    n_process = doc.page_count if config.MAX_PAGES == 0 else min(doc.page_count, config.MAX_PAGES)
    idx = 0
    try:
        for pno in range(n_process):
            if len(figs) >= max_per_doc:
                break
            page = doc.load_page(pno)
            for clip, cap in _caption_clips(page):
                if len(figs) >= max_per_doc:
                    break
                try:
                    pix = page.get_pixmap(clip=clip, dpi=config.FIGURE_DPI)
                    png = pix.tobytes("png")
                except Exception:
                    continue
                if _ink_fraction(png) < config.FIGURE_MIN_INK_FRAC:
                    continue  # blank band — caption with no real figure above it
                try:
                    vjpg, vw, vh = _resize_jpeg(png, config.FIGURE_MAX_PX, quality=80)
                except Exception:
                    continue
                figs.append(Figure(
                    doc_id=src.id, page=pno + 1, index=idx, caption_text=cap,
                    image_bytes=png, vision_bytes=vjpg,
                    meta={"w": vw, "h": vh},
                ))
                idx += 1
    finally:
        doc.close()

    # Persist: full-res → storage (bronze); thumbnail → public dir (committed, small).
    config.PUBLIC_FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    for f in figs:
        key = f"figures/{f.doc_id}/p{f.page}_{f.index}.png"
        try:
            storage.put_bytes(key, f.image_bytes)
            f.storage_uri = storage.uri(key)
        except Exception:
            f.storage_uri = ""
        thumb, _, _ = _resize_jpeg(f.image_bytes, config.THUMB_MAX_PX, quality=72)
        name = f"{f.doc_id}_p{f.page}_{f.index}.jpg"
        (config.PUBLIC_FIGURES_DIR / name).write_bytes(thumb)
        f.thumb_rel = f"/data/figures/{name}"
    return figs


def reset_public_figures() -> None:
    """Clear committed thumbnails at the start of a run so stale figures don't accumulate."""
    d = config.PUBLIC_FIGURES_DIR
    if d.exists():
        for p in d.glob("*.jpg"):
            p.unlink()
    d.mkdir(parents=True, exist_ok=True)

"""Stage 3 — Parse (multimodal). Extract text + tables + images + formulas from a PDF.

Near-zero by default (no ML): PyMuPDF pulls text, tables (its geometry-based
``find_tables``) and embedded images in a single pass; a light heuristic flags
formula-dense blocks. Tesseract OCR is a *fallback* only — it fires when a page has no
extractable text (a scanned page), and the page is flagged ``ocr_used``.

Using PyMuPDF for tables (not pdfplumber) keeps the dependency set free of the
pillow-version clash with fastembed, and means one library covers text+tables+images.

Images are saved to object storage (bronze/images) and referenced by path; captioning
them is the phase-2 vision step. Every extracted unit keeps its page number for lineage.
"""

from __future__ import annotations

import io

from ingestion import config
from ingestion.state import Block, FetchedDoc, ParsedDoc
from ingestion.storage import Storage

# Math indicators for the formula heuristic — operators, relations and Greek letters
# dense in equations but sparse in prose.
_MATH_CHARS = set("∑∫√∞±×÷≤≥≠≈∈∉⊂⊃∪∩∇∂∆ΣΠΩαβγδεθλμστφψωρ→←↔⇒∀∃")
_MATH_TOKENS = ("\\frac", "\\sum", "\\int", "\\sqrt", "\\alpha", "\\beta", "\\sigma")


def _looks_like_formula(line: str) -> bool:
    s = line.strip()
    if len(s) < 3:
        return False
    math_hits = sum(1 for ch in s if ch in _MATH_CHARS)
    token_hits = sum(t in s for t in _MATH_TOKENS)
    return math_hits >= 2 or token_hits >= 1


def _ocr_page(page) -> str:
    """Fallback OCR for a text-less page. Returns '' if Tesseract isn't available."""
    try:
        import pytesseract
        from PIL import Image
    except Exception:
        return ""
    try:
        pix = page.get_pixmap(dpi=200)
        return pytesseract.image_to_string(Image.open(io.BytesIO(pix.tobytes("png")))) or ""
    except Exception:
        return ""


def _page_tables(page) -> list[str]:
    """Tables on a page rendered as pipe-delimited text (PyMuPDF geometry finder)."""
    out: list[str] = []
    try:
        finder = page.find_tables()
    except Exception:
        return out
    for tb in getattr(finder, "tables", []):
        try:
            rows = tb.extract()
        except Exception:
            continue
        rendered = [
            " | ".join((str(c).strip() if c is not None else "") for c in row)
            for row in rows
            if any(c not in (None, "") for c in row)
        ]
        if len(rendered) >= 2:  # ignore 1-row false positives
            out.append("\n".join(rendered))
    return out


def parse_pdf(fetched: FetchedDoc, storage: Storage) -> ParsedDoc:
    import fitz  # PyMuPDF

    src = fetched.source
    doc = fitz.open(fetched.local_path)
    blocks: list[Block] = []
    n_images = n_tables = 0
    ocr_used = has_math = False

    # Bound the expensive work: find_tables() is ~1.3s/page, so cap pages parsed and
    # only scan the early pages for tables (where paper tables actually appear).
    total_pages = doc.page_count
    n_process = total_pages if config.MAX_PAGES == 0 else min(total_pages, config.MAX_PAGES)

    for pno in range(n_process):
        page = doc.load_page(pno)

        # --- text (with OCR fallback for scanned pages) ---
        text = page.get_text("text").strip()
        if len(text) < 20:
            ocr = _ocr_page(page)
            if ocr.strip():
                text, ocr_used = ocr.strip(), True
        if text:
            prose, formulas = [], []
            for line in text.splitlines():
                (formulas if _looks_like_formula(line) else prose).append(line)
            if any(p.strip() for p in prose):
                blocks.append(Block(kind="text", text="\n".join(prose).strip(), page=pno + 1))
            if formulas:
                has_math = True
                blocks.append(Block(kind="formula", text="\n".join(formulas).strip(),
                                    page=pno + 1, meta={"n_lines": len(formulas)}))

        # --- tables (only scan early pages — expensive geometry pass) ---
        if pno < config.TABLE_SCAN_MAX_PAGES:
            for j, tbl in enumerate(_page_tables(page)):
                blocks.append(Block(kind="table", text=tbl, page=pno + 1, meta={"index": j}))
                n_tables += 1

        # --- images (skip tiny icons/logos) ---
        for k, img in enumerate(page.get_images(full=True)):
            xref = img[0]
            try:
                base = doc.extract_image(xref)
            except Exception:
                continue
            if base.get("width", 0) < 100 or base.get("height", 0) < 100:
                continue
            key = f"images/{src.id}/p{pno + 1}_{k}.{base.get('ext', 'png')}"
            storage.put_bytes(key, base["image"])
            n_images += 1
            blocks.append(Block(kind="image", text="", page=pno + 1,
                                image_path=storage.uri(key),
                                meta={"w": base.get("width"), "h": base.get("height")}))

    parsed = ParsedDoc(
        source_id=src.id, title=src.title, pdf_url=src.pdf_url,
        n_pages=total_pages, pages_processed=n_process, blocks=blocks, n_images=n_images,
        n_tables=n_tables, has_math=has_math, ocr_used=ocr_used, parser="pymupdf",
    )
    doc.close()
    return parsed

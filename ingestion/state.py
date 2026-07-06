"""Typed data contracts that flow between pipeline stages.

Every boundary is a pydantic model — a malformed hand-off is caught here rather than
corrupting the index downstream. The LangGraph ``PipelineState`` is the accumulating
graph state; individual documents move through it as they gain fields stage by stage.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Optional, TypedDict

from pydantic import BaseModel, Field

BlockKind = Literal["text", "table", "formula", "image"]


class SourceDoc(BaseModel):
    """A discovered source, before anything is downloaded."""
    id: str                                   # e.g. arXiv id '2607.01705v1'
    title: str
    abstract: str = ""
    pdf_url: str
    categories: list[str] = Field(default_factory=list)
    published: str = ""
    source_type: str = "arxiv_pdf"


class FetchedDoc(BaseModel):
    """A source after fetch: raw bytes on disk (bronze), content-addressed."""
    source: SourceDoc
    local_path: str
    sha256: str
    n_bytes: int
    from_cache: bool = False


class Block(BaseModel):
    """One extracted unit of content with provenance back to a page."""
    kind: BlockKind
    text: str = ""                            # text / table-as-text / formula text / image caption
    page: int = 0
    image_path: Optional[str] = None          # set for kind == 'image'
    meta: dict[str, Any] = Field(default_factory=dict)


class ParsedDoc(BaseModel):
    """A document after multimodal parsing (silver layer)."""
    source_id: str
    title: str
    pdf_url: str
    n_pages: int = 0                          # total pages in the PDF
    pages_processed: int = 0                  # pages actually parsed (may be capped for speed)
    blocks: list[Block] = Field(default_factory=list)
    n_images: int = 0
    n_tables: int = 0
    n_captioned: int = 0                      # figures rasterized + vision-captioned (sub-project A)
    has_math: bool = False
    ocr_used: bool = False
    parser: str = "pymupdf"


class Chunk(BaseModel):
    """A gold-layer chunk: what actually gets embedded + indexed."""
    id: int
    doc_id: str
    title: str
    source_url: str
    text: str
    kind: BlockKind = "text"
    page: int = 0
    sha256: str = ""                          # dedup key
    topics: list[str] = Field(default_factory=list)
    summary: str = ""
    image_path: Optional[str] = None


class Reject(BaseModel):
    """A dead-letter record — nothing is dropped silently; every reject has a reason."""
    ref: str                                  # doc id or chunk id
    stage: str                                # discover|fetch|parse|enrich|quality
    reason: str


class PipelineState(TypedDict, total=False):
    """Accumulating LangGraph state. Lists grow as documents progress through stages."""
    run_id: str
    sources: list[dict]        # SourceDoc dumps
    fetched: list[dict]        # FetchedDoc dumps
    parsed: list[dict]         # ParsedDoc dumps
    chunks: list[dict]         # Chunk dumps (post-enrich)
    accepted: list[dict]       # Chunk dumps that passed the quality gate
    rejects: list[dict]        # Reject dumps
    indexed: int               # count upserted to Qdrant
    spent_usd: float           # running LLM spend (bounded by TOKEN_BUDGET_USD)
    stats: dict[str, Any]      # per-stage counters for the manifest

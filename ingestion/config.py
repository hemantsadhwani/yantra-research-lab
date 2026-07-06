"""Pipeline configuration and the medallion directory layout.

Everything is overridable by env var so the same code runs locally and in CI. Paths are
anchored to this package so `python -m ingestion.run` works from anywhere.
"""

from __future__ import annotations

import os
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent
REPO_ROOT = PKG_DIR.parent

# --- Medallion data layout (bronze = raw, silver = parsed, gold = indexed) ---
DATA_DIR = Path(os.environ.get("INGEST_DATA_DIR", PKG_DIR / "data"))
BRONZE_DIR = DATA_DIR / "raw"          # raw PDFs, kept, keyed by content hash (git-ignored)
SILVER_DIR = DATA_DIR / "parsed"       # extracted text/tables/images json (git-ignored)
IMAGES_DIR = DATA_DIR / "images"       # extracted figures (git-ignored)
CATALOG_PATH = DATA_DIR / "catalog.json"          # lineage catalog (git-ignored, durable locally/CI)
STATE_DIR = DATA_DIR / "state"         # langgraph checkpoints (git-ignored)

# The committed public artifact the site renders (small, safe, no raw content).
MANIFEST_PATH = Path(
    os.environ.get("INGEST_MANIFEST_PATH", REPO_ROOT / "frontend" / "public" / "data" / "ingestion.json")
)

# --- Source discovery (arXiv q-fin: open access, math + tables + figures) ---
ARXIV_CATEGORIES = os.environ.get(
    "INGEST_ARXIV_CATS",
    "q-fin.TR,q-fin.ST,q-fin.PM,q-fin.RM,q-fin.CP,q-fin.MF,q-fin.PR",
).split(",")
CORPUS_SIZE = int(os.environ.get("INGEST_CORPUS_SIZE", "10"))
ARXIV_API = os.environ.get("INGEST_ARXIV_API", "https://export.arxiv.org/api/query")

# --- Indexing (MUST mirror backend/embeddings.py so query-time vectors align) ---
COLLECTION = os.environ.get("INGEST_COLLECTION", "research_corpus")  # separate from live 'methodology'
EMBED_MODEL = os.environ.get("EMBED_MODEL", "BAAI/bge-small-en-v1.5")

# --- Parsing performance bounds (find_tables is ~1.3s/page; cap the expensive work) ---
MAX_PAGES = int(os.environ.get("INGEST_MAX_PAGES", "24"))          # pages parsed per doc; 0 = all
TABLE_SCAN_MAX_PAGES = int(os.environ.get("INGEST_TABLE_MAX_PAGES", "10"))  # tables live early in papers

# --- Chunking ---
CHUNK_WORDS = int(os.environ.get("INGEST_CHUNK_WORDS", "380"))
OVERLAP_WORDS = int(os.environ.get("INGEST_OVERLAP_WORDS", "60"))

# --- Enrichment / cost controls (bounded autonomy) ---
ENRICH_MODEL = os.environ.get("INGEST_ENRICH_MODEL", "claude-haiku-4-5")
ENRICH_MAX_TOKENS = int(os.environ.get("INGEST_ENRICH_MAX_TOKENS", "400"))
TOKEN_BUDGET_USD = float(os.environ.get("INGEST_TOKEN_BUDGET_USD", "3.0"))  # hard cap per run
FETCH_RETRIES = int(os.environ.get("INGEST_FETCH_RETRIES", "3"))
NODE_RETRIES = int(os.environ.get("INGEST_NODE_RETRIES", "3"))

# --- Sub-project A: figure extraction + vision captioning (multimodal retrieval) ---
# Figures are found by anchoring on "Figure N" captions and rasterizing the band above
# them (catches vector figures that get_images misses). Each is captioned by a bounded
# vision call, then embedded by its caption. Counts are capped to bound cost + repo size.
CAPTION_FIGURES = os.environ.get("INGEST_CAPTION_FIGURES", "1") == "1"
VISION_MODEL = os.environ.get("INGEST_VISION_MODEL", "claude-haiku-4-5")  # 4.x Haiku is multimodal
VISION_MAX_TOKENS = int(os.environ.get("INGEST_VISION_MAX_TOKENS", "220"))
MAX_FIGURES_PER_DOC = int(os.environ.get("INGEST_MAX_FIGURES_PER_DOC", "4"))
MAX_FIGURES_TOTAL = int(os.environ.get("INGEST_MAX_FIGURES_TOTAL", "18"))  # caps committed thumbnails
FIGURE_DPI = int(os.environ.get("INGEST_FIGURE_DPI", "110"))       # render DPI for the figure band
FIGURE_MAX_PX = int(os.environ.get("INGEST_FIGURE_MAX_PX", "1024"))  # cap sent-to-vision long edge
THUMB_MAX_PX = int(os.environ.get("INGEST_THUMB_MAX_PX", "512"))   # public thumbnail long edge
FIGURE_MIN_BAND_FRAC = float(os.environ.get("INGEST_FIGURE_MIN_BAND_FRAC", "0.05"))  # min band height
FIGURE_MAX_BAND_FRAC = float(os.environ.get("INGEST_FIGURE_MAX_BAND_FRAC", "0.62"))  # max band height
FIGURE_FALLBACK_BAND_FRAC = float(os.environ.get("INGEST_FIGURE_FALLBACK_BAND_FRAC", "0.33"))  # no-geometry band
FIGURE_MIN_INK_FRAC = float(os.environ.get("INGEST_FIGURE_MIN_INK_FRAC", "0.012"))   # skip blank bands

# Public thumbnails the site renders (committed, small). Full-res PNGs live in S3 bronze.
PUBLIC_FIGURES_DIR = Path(
    os.environ.get("INGEST_PUBLIC_FIGURES_DIR", REPO_ROOT / "frontend" / "public" / "data" / "figures")
)

# Polite crawling — arXiv asks for a descriptive UA and >=3s between API hits.
USER_AGENT = os.environ.get(
    "INGEST_USER_AGENT", "yantra-research-lab/1.0 (ingestion; +https://yantra-research-lab.vercel.app)"
)


def ensure_dirs() -> None:
    for d in (BRONZE_DIR, SILVER_DIR, IMAGES_DIR, STATE_DIR, MANIFEST_PATH.parent):
        d.mkdir(parents=True, exist_ok=True)

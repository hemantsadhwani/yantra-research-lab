"""Corpus ingestion: load markdown, chunk, embed, and index.

Sources (methodology / general knowledge ONLY):
  - the repo's ``knowledge_base/`` folder, if present, and
  - the built-in ``seed_corpus/`` notes shipped alongside this file.

GUARDRAIL (critical, defense in depth): this index must NEVER contain anything
resembling proprietary strategy parameters, thresholds, or entry/exit logic. The
corpus is general quant *methodology* only. Even if a private note were dropped into
``knowledge_base/``, the chat endpoint's ``should_refuse`` policy is a second line of
defence — but the honest fix is to keep such content out of the corpus in the first
place. Do not add strategy configs here.

Run:  python backend/ingest.py
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

from retriever import Chunk, get_retriever

load_dotenv(find_dotenv())

BACKEND_DIR = Path(__file__).resolve().parent
REPO_ROOT = BACKEND_DIR.parent
SEED_DIR = BACKEND_DIR / "seed_corpus"
KB_DIR = REPO_ROOT / "knowledge_base"

# Below this many knowledge_base docs we consider the KB "sparse" and always fold in
# the built-in seed corpus so the bot has enough grounding to be useful.
SPARSE_KB_THRESHOLD = 12

# ~500-token chunks with overlap. We approximate tokens as words (~0.75 words/token),
# so ~380 words ≈ 500 tokens; 60-word overlap preserves context across boundaries.
CHUNK_WORDS = 380
OVERLAP_WORDS = 60


def _iter_markdown(folder: Path) -> list[Path]:
    if not folder.exists():
        return []
    return sorted(p for p in folder.rglob("*.md") if p.is_file())


def _chunk_text(text: str) -> list[str]:
    words = text.split()
    if not words:
        return []
    chunks: list[str] = []
    step = max(1, CHUNK_WORDS - OVERLAP_WORDS)
    for start in range(0, len(words), step):
        window = words[start : start + CHUNK_WORDS]
        if window:
            chunks.append(" ".join(window))
        if start + CHUNK_WORDS >= len(words):
            break
    return chunks


def _title_for(path: Path) -> str:
    """Use the first markdown H1 as the title, else a prettified filename."""
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("# "):
                return line[2:].strip()
    except OSError:
        pass
    return path.stem.replace("-", " ").replace("_", " ").title()


def build_chunks() -> list[Chunk]:
    kb_files = _iter_markdown(KB_DIR)
    seed_files = _iter_markdown(SEED_DIR)

    files: list[Path] = list(kb_files)
    if len(kb_files) < SPARSE_KB_THRESHOLD:
        # Sparse (or empty) knowledge base — include the seed corpus too.
        files += seed_files
    # De-duplicate while preserving order.
    seen: set[Path] = set()
    ordered = [f for f in files if not (f in seen or seen.add(f))]

    chunks: list[Chunk] = []
    cid = 0
    for path in ordered:
        try:
            body = path.read_text(encoding="utf-8")
        except OSError:
            continue
        title = _title_for(path)
        rel = str(path.relative_to(REPO_ROOT)) if REPO_ROOT in path.parents else path.name
        for piece in _chunk_text(body):
            chunks.append(Chunk(id=cid, text=piece, title=title, source=rel))
            cid += 1
    return chunks


def main() -> None:
    chunks = build_chunks()
    if not chunks:
        raise SystemExit(
            "No documents found to index. Add markdown to knowledge_base/ or "
            "seed_corpus/."
        )
    backend = os.environ.get("VECTOR_BACKEND", "qdrant")
    print(f"Ingesting {len(chunks)} chunks into VECTOR_BACKEND={backend!r} ...")
    retriever = get_retriever()
    retriever.index(chunks)
    print(f"Done. Indexed {len(chunks)} chunks.")
    titles = sorted({c.title for c in chunks})
    print(f"Sources: {len(titles)} document(s):")
    for t in titles:
        print(f"  - {t}")


if __name__ == "__main__":
    main()

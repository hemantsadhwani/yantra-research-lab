"""Stage 2 — Fetch. Download raw PDFs into the bronze layer, content-addressed.

Idempotent + incremental: a PDF already in storage is served from cache (no network),
so daily re-runs are cheap. Transient network failures retry with backoff; a source that
still fails is dead-lettered (a Reject) rather than crashing the run.

NOTE (future private sources): fetch is deliberately source-agnostic — it takes any
``SourceDoc`` with a URL. A private connector (repo export, P&L feed) would produce
``SourceDoc``s the same way; only Discover changes.
"""

from __future__ import annotations

import hashlib
import time

import httpx

from ingestion import config
from ingestion.state import FetchedDoc, Reject, SourceDoc
from ingestion.storage import Storage


def _download(url: str) -> bytes:
    """GET with bounded exponential backoff. Raises on final failure."""
    last: Exception | None = None
    for attempt in range(config.FETCH_RETRIES):
        try:
            r = httpx.get(
                url,
                headers={"User-Agent": config.USER_AGENT},
                timeout=60,
                follow_redirects=True,
            )
            r.raise_for_status()
            return r.content
        except Exception as e:  # noqa: BLE001 — network/HTTP; retry then give up
            last = e
            if attempt < config.FETCH_RETRIES - 1:
                time.sleep(1.5 * (attempt + 1))  # 1.5s, 3s, …
    raise last  # type: ignore[misc]


def fetch_one(source: SourceDoc, storage: Storage) -> FetchedDoc:
    key = f"raw/{source.id}.pdf"
    if storage.exists(key):
        data = storage.get_bytes(key)
        return FetchedDoc(
            source=source,
            local_path=str(storage.local_file(key)),
            sha256=hashlib.sha256(data).hexdigest(),
            n_bytes=len(data),
            from_cache=True,
        )
    data = _download(source.pdf_url)
    if not data[:5].startswith(b"%PDF"):  # basic content check — did we get a PDF?
        raise ValueError(f"{source.id}: response is not a PDF (got {len(data)} bytes)")
    storage.put_bytes(key, data)
    return FetchedDoc(
        source=source,
        local_path=str(storage.local_file(key)),
        sha256=hashlib.sha256(data).hexdigest(),
        n_bytes=len(data),
        from_cache=False,
    )


def fetch(sources: list[SourceDoc], storage: Storage) -> tuple[list[FetchedDoc], list[Reject]]:
    fetched: list[FetchedDoc] = []
    rejects: list[Reject] = []
    for src in sources:
        try:
            fetched.append(fetch_one(src, storage))
        except Exception as e:  # noqa: BLE001
            rejects.append(Reject(ref=src.id, stage="fetch", reason=str(e)[:200]))
        time.sleep(0.2)  # be polite to the host
    return fetched, rejects

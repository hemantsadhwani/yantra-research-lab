"""Stage 1 — Discover. Query the arXiv API for recent open-access q-fin papers.

Returns a list of ``SourceDoc`` (metadata + PDF url) — no downloads yet. Real source
*discovery* rather than a hardcoded list: the corpus refreshes itself each run, and
we never ship arXiv IDs that might 404.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import httpx

from ingestion import config
from ingestion.state import SourceDoc

_ATOM = {"a": "http://www.w3.org/2005/Atom"}


def discover(limit: int | None = None) -> list[SourceDoc]:
    limit = limit or config.CORPUS_SIZE
    query = " OR ".join(f"cat:{c.strip()}" for c in config.ARXIV_CATEGORIES)
    params = {
        "search_query": query,
        "start": 0,
        # over-fetch a little so we still hit `limit` after any malformed entries
        "max_results": limit + 10,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    resp = httpx.get(
        config.ARXIV_API,
        params=params,
        headers={"User-Agent": config.USER_AGENT},
        timeout=30,
        follow_redirects=True,
    )
    resp.raise_for_status()
    root = ET.fromstring(resp.text)

    out: list[SourceDoc] = []
    for entry in root.findall("a:entry", _ATOM):
        pdf_url = None
        for link in entry.findall("a:link", _ATOM):
            if link.get("title") == "pdf" or link.get("type") == "application/pdf":
                pdf_url = link.get("href")
        if not pdf_url:
            continue
        aid = (entry.find("a:id", _ATOM).text or "").rsplit("/", 1)[-1]
        title = " ".join((entry.find("a:title", _ATOM).text or "").split())
        abstract = " ".join((entry.find("a:summary", _ATOM).text or "").split())
        published = (entry.find("a:published", _ATOM).text or "")[:10]
        cats = [c.get("term") for c in entry.findall("a:category", _ATOM) if c.get("term")]
        # arXiv PDF links are http; normalise to https so fetch doesn't chase a redirect.
        pdf_url = pdf_url.replace("http://", "https://")
        out.append(
            SourceDoc(
                id=aid, title=title, abstract=abstract, pdf_url=pdf_url,
                categories=cats, published=published, source_type="arxiv_pdf",
            )
        )
        if len(out) >= limit:
            break
    return out


if __name__ == "__main__":  # quick manual check
    docs = discover()
    print(f"discovered {len(docs)} sources")
    for d in docs[:5]:
        print(f"  {d.id:16s} {','.join(d.categories[:2]):18s} {d.title[:60]}")

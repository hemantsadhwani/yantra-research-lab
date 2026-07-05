"""Stage 5 — Quality gate (governance). Nothing reaches the index without passing.

Three checks, each producing a *reasoned* reject (dead-letter) rather than a silent drop:
  1. Dedup — exact-content hash; the same passage twice is wasteful and skews retrieval.
  2. Relevance — drop boilerplate/fragments (references, headers, junk OCR).
  3. IP-leak quarantine — the privacy boundary made mechanical. Public arXiv won't trip
     it, but when a *private* connector (trading-bot repo, P&L feed) is added later, any
     chunk that discloses proprietary strategy logic/params is quarantined here so it can
     never be published. Numbers-only (e.g. P&L) are allowed; logic + params are not.

Schema validity is already guaranteed upstream (chunks are pydantic models); this stage
adds semantic/policy gates on top.
"""

from __future__ import annotations

import re

from ingestion.state import Chunk, Reject

# Names of the proprietary strategies (see the 'one contract, two engines' seam). Their
# presence ALONGSIDE concrete parameter/threshold disclosure is what we quarantine.
_PROPRIETARY_NAMES = ("nifty-weekday", "nifty weekday", "nifty-expiry", "nifty expiry",
                      "sensex-expiry", "sensex expiry")
_PARAM_MARKERS = ("z_entry", "z_exit", "stop_pct", "lookback", "entry threshold",
                  "exit threshold", "stop loss", "stop-loss")
_NUM = re.compile(r"\d")


def _is_relevant(text: str) -> bool:
    s = text.strip()
    if len(s) < 60:
        return False
    letters = sum(c.isalpha() for c in s)
    if letters / max(len(s), 1) < 0.5:          # mostly numbers/symbols → likely a stray fragment
        return False
    lower = s.lower()
    if lower.startswith(("references", "bibliography", "acknowledg")):
        return False
    return True


def _looks_like_ip(text: str) -> bool:
    """Quarantine only if a proprietary strategy is named AND concrete params/thresholds
    are disclosed — publishing the *edge*. Numbers alone (P&L) are fine."""
    lower = text.lower()
    named = any(n in lower for n in _PROPRIETARY_NAMES)
    if not named:
        return False
    discloses_params = any(m in lower for m in _PARAM_MARKERS) and bool(_NUM.search(text))
    return discloses_params


def quality_gate(chunks: list[Chunk]) -> tuple[list[Chunk], list[Reject]]:
    accepted: list[Chunk] = []
    rejects: list[Reject] = []
    seen: set[str] = set()
    for c in chunks:
        ref = f"{c.doc_id}#{c.id}"
        if c.sha256 in seen:
            rejects.append(Reject(ref=ref, stage="quality", reason="duplicate"))
            continue
        if _looks_like_ip(c.text):
            rejects.append(Reject(ref=ref, stage="quality", reason="ip-leak-quarantine"))
            continue
        if not _is_relevant(c.text):
            rejects.append(Reject(ref=ref, stage="quality", reason="low-relevance"))
            continue
        seen.add(c.sha256)
        accepted.append(c)
    return accepted, rejects

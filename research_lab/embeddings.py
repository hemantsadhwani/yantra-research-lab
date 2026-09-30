"""Text embeddings for semantic memory — fastembed when available, stdlib otherwise.

``embed(text)`` returns a unit-length vector. Two backends, chosen lazily on first use:

* **fastembed** (``BAAI/bge-small-en-v1.5``, 384-dim) when the optional ``memory`` extra
  is installed and ``$YANTRA_EMBEDDER`` is not ``"hashed"``. The model is loaded once and
  cached. If it cannot be loaded (no network for the first download, broken install) the
  module falls back to the hashed backend for the rest of the process and says so on
  stderr — a degraded embedder must never look like the real one, which is why every
  stored vector is tagged with ``embedder_name()``.
* **hashed bag-of-words** (256-dim, stdlib ``hashlib``): lowercase word tokens hashed
  into buckets with a sign bit, then L2-normalised. Deterministic across processes and
  platforms, no downloads — the default for tests and CI (``YANTRA_EMBEDDER=hashed``).
  It captures lexical overlap, not meaning; that is enough for "recall trials whose
  rationale and parameters read like this one", and it is honest about being cheap.

Nothing here imports fastembed at module import time, so the stdlib path stays stdlib.
"""

from __future__ import annotations

import hashlib
import importlib.util
import math
import os
import re
import sys
from typing import Any

HASHED_DIM = 256
HASHED_NAME = "hashed-bow-256"
FASTEMBED_NAME = "fastembed:bge-small"
FASTEMBED_MODEL = "BAAI/bge-small-en-v1.5"

_TOKEN = re.compile(r"[a-z0-9_.\-]+")
_model: Any = None
_fastembed_failed = False


def _want_fastembed() -> bool:
    if _fastembed_failed or os.environ.get("YANTRA_EMBEDDER", "").lower() == "hashed":
        return False
    return importlib.util.find_spec("fastembed") is not None


def embedder_name() -> str:
    """Name of the backend ``embed`` will use right now (stored alongside each vector)."""
    return FASTEMBED_NAME if _want_fastembed() else HASHED_NAME


def _hashed(text: str) -> list[float]:
    vec = [0.0] * HASHED_DIM
    for tok in _TOKEN.findall(text.lower()):
        h = int.from_bytes(hashlib.blake2b(tok.encode(), digest_size=8).digest(), "big")
        vec[h % HASHED_DIM] += 1.0 if (h >> 32) & 1 else -1.0
    return _normalise(vec)


def _normalise(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    return [x / norm for x in vec] if norm else vec


def _fastembed(text: str) -> list[float]:
    global _model
    if _model is None:
        from fastembed import TextEmbedding  # lazy: optional extra

        _model = TextEmbedding(FASTEMBED_MODEL)
    return _normalise([float(x) for x in next(iter(_model.embed([text])))])


def embed(text: str) -> list[float]:
    """Embed ``text`` as a unit vector with the backend named by ``embedder_name()``."""
    global _fastembed_failed
    if _want_fastembed():
        try:
            return _fastembed(text)
        except Exception as e:  # noqa: BLE001 - offline first download, broken install
            _fastembed_failed = True
            print(f"  ! fastembed unavailable ({type(e).__name__}: {e}); "
                  f"using {HASHED_NAME}", file=sys.stderr)
    return _hashed(text)


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity; 0.0 for mismatched lengths or zero vectors."""
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0

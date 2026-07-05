"""Local text embeddings via fastembed (ONNX, no torch, no API key).

Wraps ``fastembed.TextEmbedding`` with the small, fast ``BAAI/bge-small-en-v1.5``
model (384-dim). The model is downloaded and cached on first use — see the README:
the first ``ingest.py`` run needs network access to fetch the ONNX weights (~130 MB),
after which everything runs fully offline.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Iterable

# bge-small-en-v1.5 produces 384-dimensional embeddings.
EMBED_MODEL = os.environ.get("EMBED_MODEL", "BAAI/bge-small-en-v1.5")
EMBED_DIM = 384


@lru_cache(maxsize=1)
def _model():
    # Imported lazily so importing this module (e.g. in tests) does not require
    # fastembed to be installed or trigger a model download.
    from fastembed import TextEmbedding

    return TextEmbedding(model_name=EMBED_MODEL)


def embed(texts: Iterable[str]) -> list[list[float]]:
    """Embed a batch of strings into a list of float vectors."""
    model = _model()
    return [[float(x) for x in vec] for vec in model.embed(list(texts))]


def embed_one(text: str) -> list[float]:
    """Embed a single string."""
    return embed([text])[0]

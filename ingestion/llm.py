"""Thin Anthropic helper for the enrichment agents, with cost accounting.

Kept tiny and self-contained so the pipeline component doesn't import the serving app.
Returns estimated USD per call so the graph can enforce a hard per-run token budget.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any, Optional

# Claude Haiku 4.5 list prices (USD / million tokens). Env-overridable.
PRICE_IN = float(os.environ.get("PRICE_INPUT_PER_MTOK", "1.0"))
PRICE_OUT = float(os.environ.get("PRICE_OUTPUT_PER_MTOK", "5.0"))

_client = None


def get_client():
    """Cached Anthropic client, or None if no API key is configured."""
    global _client
    if _client is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return None
        import anthropic

        _client = anthropic.Anthropic()
    return _client


def estimate_cost(usage) -> float:
    if usage is None:
        return 0.0
    inp = int(getattr(usage, "input_tokens", 0) or 0)
    out = int(getattr(usage, "output_tokens", 0) or 0)
    return round((inp * PRICE_IN + out * PRICE_OUT) / 1_000_000, 6)


def _strip_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[-1]
        if s.endswith("```"):
            s = s.rsplit("```", 1)[0]
    return s.strip()


def complete_json(system: str, user: str, model: str, max_tokens: int) -> tuple[Optional[dict[str, Any]], float]:
    """Call the model and parse a JSON object from its reply.

    Returns (parsed_or_None, cost_usd). Never raises — a bad/unparseable reply yields
    (None, cost) so the caller can fall back to deterministic metadata.
    """
    client = get_client()
    if client is None:
        return None, 0.0
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
        cost = estimate_cost(getattr(resp, "usage", None))
        try:
            return json.loads(_strip_fences(text)), cost
        except Exception:
            return None, cost
    except Exception:
        return None, 0.0


def caption_image(system: str, user: str, image_bytes: bytes, media_type: str,
                  model: str, max_tokens: int) -> tuple[Optional[str], float]:
    """Vision call: describe a figure image. Returns (caption_or_None, cost_usd).

    Never raises — a missing key or API error yields (None, cost) so the caller can fall
    back to the figure's own printed caption text. Image input tokens are billed at the
    same input rate; keep images small (see FIGURE_MAX_PX) to stay near-zero.
    """
    client = get_client()
    if client is None:
        return None, 0.0
    try:
        b64 = base64.b64encode(image_bytes).decode("ascii")
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
                {"type": "text", "text": user},
            ]}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        cost = estimate_cost(getattr(resp, "usage", None))
        return (text or None), cost
    except Exception:
        return None, 0.0

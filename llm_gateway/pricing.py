"""USD per million tokens, for cost *estimates* (list price, not an invoice).

Bedrock bills the same Claude models at the same list price in the main regions, so a
Bedrock model id containing ``haiku-4-5`` maps to the Haiku 4.5 row and is labelled
"list price". Ollama runs locally and costs 0. Anything unknown estimates to 0 and logs
one warning, so a missing row shows up in the logs rather than as a silently wrong bill.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("llm_gateway.pricing")

# model -> (input, output, cache_read, cache_write) USD per million tokens
PRICES: dict[str, tuple[float, float, float, float]] = {
    "claude-haiku-4-5": (1.00, 5.00, 0.10, 1.25),
}
PRICE_LABEL = "list price"

_warned: set[str] = set()


def _row(model: str) -> tuple[float, float, float, float] | None:
    if model in PRICES:
        return PRICES[model]
    if "haiku-4-5" in model:          # e.g. us.anthropic.claude-haiku-4-5-20251001-v1:0
        return PRICES["claude-haiku-4-5"]
    return None


def estimate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float:
    """Estimated USD for one call at list price; 0 for an unknown model."""
    row = _row(model)
    if row is None:
        if model not in _warned:
            _warned.add(model)
            logger.warning("no price for model %r; estimating its cost as $0", model)
        return 0.0
    p_in, p_out, p_read, p_write = row
    return (
        input_tokens * p_in
        + output_tokens * p_out
        + cache_read_tokens * p_read
        + cache_write_tokens * p_write
    ) / 1_000_000

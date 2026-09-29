"""Pydantic schemas for model replies — the only place the research loop uses pydantic.

``schemas.py`` stays stdlib dataclasses so the default path imports nothing; this
module is imported lazily, inside the LLM proposer, and nowhere else on that path.
Validation here is *shape* only (the four parameters present and numeric, at least one
variant): range enforcement stays with ``_clamp`` and ``verify_variant``, because a model
that proposes ``lookback=900`` should cost a clamp, not a rejected batch.

``params`` is an explicit model, NOT ``dict[str, float]``: structured-output decoding
closes every object (``additionalProperties: false``), so a free-form dict becomes an
object with no allowed keys and the model can only emit ``"params": {}`` -- which
``_clamp`` would silently fill from the heuristic's sample. A live run showed exactly
that; ``test_proposal_schema_survives_strict_transform`` guards it.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ProposalParams(BaseModel):
    """One value per key of ``synthetic_engine.PARAM_SPACE`` (ranges enforced later)."""

    lookback: float
    z_entry: float
    z_exit: float
    stop_pct: float


class Proposal(BaseModel):
    params: ProposalParams
    rationale: str


class ProposalBatch(BaseModel):
    variants: list[Proposal] = Field(min_length=1)

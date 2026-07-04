"""Typed I/O contracts for the agents.

Standard-library dataclasses so a fresh clone runs with zero dependencies. In the
production build these become Pydantic v2 models (validation + structured LLM output);
the field shapes are identical so the swap is mechanical. See ADR-0003.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class StrategyVariant:
    """A candidate strategy the proposer wants to test."""
    id: str
    params: dict[str, float]
    rationale: str
    parent_id: Optional[str] = None   # the variant this was derived from (memory-guided)


@dataclass
class BacktestResult:
    variant_id: str
    total_return_pct: float
    trades: int
    win_rate: float
    max_drawdown_pct: float
    sharpe: float


@dataclass
class Evaluation:
    variant_id: str
    score: float
    verdict: str          # "promote?" | "hold" | "reject"
    beats_baseline: bool
    notes: str = ""


@dataclass
class RankedVariant:
    variant: StrategyVariant
    result: BacktestResult
    evaluation: Evaluation


@dataclass
class RunResult:
    iterations: int
    variants_tested: int
    baseline: BacktestResult
    ranked: list[RankedVariant] = field(default_factory=list)   # best first

    @property
    def best(self) -> Optional[RankedVariant]:
        return self.ranked[0] if self.ranked else None

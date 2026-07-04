"""Agent memory.

Tier-1 is episodic "best-so-far" memory that steers the proposer toward what worked
(exploit) while leaving room to explore. The production build layers semantic memory
(distilled "what kinds of variants tend to win") and procedural memory (learned
heuristics) over a SQLite + sqlite-vec store. See ADR-0003.
"""

from __future__ import annotations

from typing import Optional

from research_lab.schemas import Evaluation, StrategyVariant


class Memory:
    def __init__(self) -> None:
        self._best: Optional[tuple[str, dict[str, float], float]] = None  # (id, params, score)

    def observe(self, variant: StrategyVariant, evaluation: Evaluation) -> None:
        if self._best is None or evaluation.score > self._best[2]:
            self._best = (variant.id, dict(variant.params), evaluation.score)

    def best_params(self) -> Optional[dict[str, float]]:
        return dict(self._best[1]) if self._best else None

    def best_id(self) -> Optional[str]:
        return self._best[0] if self._best else None

    def best_score(self) -> Optional[float]:
        return self._best[2] if self._best else None

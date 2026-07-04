"""Proposer agent — generates candidate strategy variants.

Tier-1 uses a deterministic, memory-guided heuristic so the loop runs offline with
no API key: it exploits around the best variant found so far and keeps one explorer
per batch. The production build swaps ``_propose_params`` for a structured LLM call
(Claude via the model gateway) that reasons about *why* to try a variant — the loop
around it is unchanged. See ADR-0003.
"""

from __future__ import annotations

import random

from research_lab.memory import Memory
from research_lab.schemas import StrategyVariant
from synthetic_engine import PARAM_SPACE


class Proposer:
    def __init__(self, seed: int = 0) -> None:
        self._rng = random.Random(seed)
        self._counter = 0

    def propose(self, n: int, memory: Memory) -> list[StrategyVariant]:
        best = memory.best_params()
        variants: list[StrategyVariant] = []
        for k in range(n):
            exploit = best is not None and k < n - 1   # always keep >=1 explorer
            if exploit:
                params = self._perturb(best)
                rationale = "memory-guided: perturb best-so-far (exploit)"
                parent = memory.best_id()
            else:
                params = self._sample()
                rationale = "exploration: sampled fresh from the param space"
                parent = None
            self._counter += 1
            variants.append(
                StrategyVariant(id=f"v{self._counter:03d}", params=params,
                                rationale=rationale, parent_id=parent)
            )
        return variants

    def _sample(self) -> dict[str, float]:
        return {k: round(self._rng.uniform(lo, hi), 3) for k, (lo, hi) in PARAM_SPACE.items()}

    def _perturb(self, base: dict[str, float]) -> dict[str, float]:
        out: dict[str, float] = {}
        for k, (lo, hi) in PARAM_SPACE.items():
            span = (hi - lo) * 0.15
            out[k] = round(min(hi, max(lo, base[k] + self._rng.uniform(-span, span))), 3)
        return out

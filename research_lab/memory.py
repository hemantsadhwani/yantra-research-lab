"""Agent memory.

Tier-1 is episodic "best-so-far" memory that steers the proposer toward what worked
(exploit) while leaving room to explore. The production build layers semantic memory
(distilled "what kinds of variants tend to win") and procedural memory (learned
heuristics) over a SQLite + sqlite-vec store. See ADR-0003.

Alongside best-so-far, ``Memory`` keeps an append-only **trial log** of every
(variant, evaluation) pair it has observed. The deterministic proposer never reads
it — it only ever needs ``best_params()`` — but an LLM proposer does: the trial log
is the raw material every context construction is built from, and the three
constructions in ``research_lab/experiments/context_study.py`` differ only in how
much of it they spend attention on. Keeping the history *outside* the context window
and deciding per-call what to include is the point: context is a budget, and memory
is the store you draw it from, not the window itself.
"""

from __future__ import annotations

from research_lab.schemas import Evaluation, StrategyVariant, Trial


class Memory:
    def __init__(self) -> None:
        self._best: tuple[str, dict[str, float], float] | None = None  # (id, params, score)
        self._trials: list[Trial] = []   # append-only history, oldest first

    def observe(self, variant: StrategyVariant, evaluation: Evaluation) -> None:
        self._trials.append(
            Trial(
                variant_id=variant.id,
                params=dict(variant.params),
                score=evaluation.score,
                verdict=evaluation.verdict,
                rationale=variant.rationale,
            )
        )
        if self._best is None or evaluation.score > self._best[2]:
            self._best = (variant.id, dict(variant.params), evaluation.score)

    def best_params(self) -> dict[str, float] | None:
        return dict(self._best[1]) if self._best else None

    def best_id(self) -> str | None:
        return self._best[0] if self._best else None

    def best_score(self) -> float | None:
        return self._best[2] if self._best else None

    def trials(self) -> list[Trial]:
        """Every (variant, evaluation) observed so far, oldest first.

        Returned as copies: a proposer building a prompt must not be able to mutate
        the loop's own record of what happened.
        """
        return [
            Trial(t.variant_id, dict(t.params), t.score, t.verdict, t.rationale)
            for t in self._trials
        ]

    def trial_count(self) -> int:
        return len(self._trials)

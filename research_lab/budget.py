"""A spend / call budget for the LLM proposer, shared by both arms (stdlib only).

Bounded autonomy has two halves: a fixed iteration count (the loop's shape) and a hard
ceiling on what the model is allowed to spend. ``Budget`` is the second half.

* ``max_usd`` caps the estimated (list-price) USD across all LLM calls in a run;
* ``max_llm_calls`` caps the number of successful model responses.

Either limit may be ``None`` (unbounded). The proposer checks ``exhausted()`` *before*
each LLM call and, once exhausted, proposes that batch with the deterministic heuristic
instead of calling the provider; it ``charge()``s the response cost *after* each call.
The loop then stops early with ``stop_reason="budget"`` (the graph arm routes straight to
the human gate / finalize; the stdlib supervisor breaks out of its iteration loop).

Enforcement is pre-call, so a run can overshoot a USD cap by at most one call's cost
(``$0.20 ≥ $0.15`` below means "the second call crossed it; no third call was made").
Only responses are charged: a provider exception carries no cost figure, and the
iteration count still bounds retries.

The stdlib supervisor keeps one ``Budget`` instance across iterations. The graph arm
cannot checkpoint an object, so ``propose`` rebuilds one per iteration with
``from_state`` and writes the numbers back (see ``research_lab/graph.py``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

INF = "∞"


@dataclass
class Budget:
    max_usd: float | None = None
    max_llm_calls: int | None = None
    spent_usd: float = 0.0
    llm_calls: int = 0

    def exhausted(self) -> bool:
        return self.reason() is not None

    def reason(self) -> str | None:
        """Which limit is exhausted, as ``"$0.2000 ≥ $0.1500"`` / ``"1 ≥ 1 llm calls"``."""
        if self.max_usd is not None and self.spent_usd >= self.max_usd:
            return f"${self.spent_usd:.4f} ≥ ${self.max_usd:.4f}"
        if self.max_llm_calls is not None and self.llm_calls >= self.max_llm_calls:
            return f"{self.llm_calls} ≥ {self.max_llm_calls} llm calls"
        return None

    def charge(self, cost_usd: float) -> None:
        """Record one completed LLM call and its (estimated) cost."""
        self.llm_calls += 1
        self.spent_usd += float(cost_usd or 0.0)

    @property
    def bounded(self) -> bool:
        return self.max_usd is not None or self.max_llm_calls is not None

    # ------------------------------------------------------------ (de)serialise
    def to_dict(self) -> dict[str, Any]:
        return {"max_usd": self.max_usd, "max_llm_calls": self.max_llm_calls,
                "spent_usd": self.spent_usd, "llm_calls": self.llm_calls}

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> Budget:
        d = d or {}
        return cls(max_usd=d.get("max_usd"), max_llm_calls=d.get("max_llm_calls"),
                   spent_usd=float(d.get("spent_usd") or 0.0),
                   llm_calls=int(d.get("llm_calls") or 0))

    def footer(self, stop_reason: str | None) -> str:
        """``budget: $0.0000/∞ · llm calls 0/∞ · stopped: iterations``."""
        max_usd = INF if self.max_usd is None else f"${self.max_usd:.4f}"
        max_calls = INF if self.max_llm_calls is None else str(self.max_llm_calls)
        stopped = stop_reason or "iterations"
        if stopped == "budget" and self.reason():
            stopped = f"budget ({self.reason()})"
        return (f"budget: ${self.spent_usd:.4f}/{max_usd} · "
                f"llm calls {self.llm_calls}/{max_calls} · stopped: {stopped}")

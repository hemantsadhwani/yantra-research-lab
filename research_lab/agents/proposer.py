"""Proposer agent — generates candidate strategy variants.

Two proposers behind one method. The deterministic path is a memory-guided heuristic
that runs offline with no API key: it exploits around the best variant found so far
and keeps one explorer per batch. When memory offers learned priors (``SqliteMemory``,
see ``research_lab/memory_store.py``), each explorer draws from that narrowed box with
probability 0.5 and from the full space otherwise. The LLM path (``use_llm=True``) replaces that
heuristic with a structured Claude call that reasons about *why* to try a variant.

**Both paths stay.** The offline one is not scaffolding to be thrown away — "it runs
reproducibly with no key" is a real property worth keeping, and having both lets the
loop answer a question most systems can't: what does putting a model in the loop
actually buy, measured on the same engine, the same baseline and the same budget?
The deterministic path remains the default for exactly that reason.

``propose(n, memory)`` is still the only public method, so the supervisor, the
schemas, the verification hooks and the evaluator are untouched by the swap — which
is the ADR-0003 claim (the loop is the spec; the agent inside a step is an
implementation detail) demonstrated rather than asserted.

The LLM path goes through ``llm_gateway`` (Anthropic direct, Claude on Bedrock, or a
local Ollama model, chosen by ``LLM_PROVIDER``) and asks for a ``ProposalBatch``: the
reply is schema-validated by the gateway before this module sees it. It still never
bypasses verification: proposals are clamped into the declared parameter space and
pass through ``verify_variant`` in the supervisor. A model that hallucinates a
``lookback`` of 900 gets corrected by the contract, not trusted. See ADR-0003.

Nothing here imports ``llm_gateway`` or pydantic at module import time — only
``_propose_llm`` does — so the heuristic default path stays stdlib-only.
"""

from __future__ import annotations

import os
import random
from typing import Any

from research_lab.agents.context import build_context
from research_lab.memory import MemoryLike
from research_lab.schemas import StrategyVariant
from synthetic_engine import PARAM_SPACE

DEFAULT_LLM_MODEL = os.environ.get("RESEARCH_MODEL", "claude-haiku-4-5")
LLM_MAX_TOKENS = 2048

# The stable prefix: identical for every call and every context construction, so a
# token delta between constructions is a delta in the *history*, not in the framing.
SYSTEM_PROMPT = """You are the proposer in an autonomous quant-research loop.

Each round you propose candidate parameter sets for a long-only mean-reversion
strategy. They are backtested on a deterministic synthetic market and scored as:

    score = total_return_pct - 0.5 * max_drawdown_pct + 40 * (win_rate - 0.5)

Your job is to propose variants that score higher than what has been tried. Reason
about *why* a direction is worth trying — which parameter you are moving, and what
you expect it to do to return, drawdown or win rate. Balance exploiting near a known
good point against exploring regions that have not been sampled.

Respond with ONLY a JSON object, no prose and no code fences:

{"variants": [{"params": {"lookback": <num>, "z_entry": <num>,
  "z_exit": <num>, "stop_pct": <num>}, "rationale": "<one short sentence>"}]}

Every parameter is required and must sit inside its declared range."""


class Proposer:
    """Propose strategy variants, deterministically or via an LLM.

    Args:
        seed: RNG seed for the deterministic path (and for the LLM path's fallback).
        use_llm: route proposals through an LLM instead of the heuristic.
        model: model id override for the LLM path (default: ``$RESEARCH_MODEL``, then
            ``$LLM_MODEL``, then the provider's default).
        provider: an ``llm_gateway`` provider. ``None`` builds one lazily from
            ``$LLM_PROVIDER`` on the first LLM call (tests inject a ``FakeProvider``).
        context_mode: which context construction to build — see ``agents/context.py``.
            Only meaningful when ``use_llm`` is set.
        start_counter: last variant number already issued, so a proposer rebuilt from a
            checkpoint (see ``research_lab/graph.py``) continues ``vNNN`` numbering.
    """

    def __init__(
        self,
        seed: int = 0,
        use_llm: bool = False,
        model: str | None = None,
        context_mode: str = "compacted",
        start_counter: int = 0,
        provider: Any = None,
    ) -> None:
        self._rng = random.Random(seed)
        self._counter = start_counter
        self.use_llm = use_llm
        self._model_override = model or os.environ.get("RESEARCH_MODEL")
        self.model = (getattr(provider, "model", None) or self._model_override
                      or DEFAULT_LLM_MODEL)
        self.context_mode = context_mode
        self._provider: Any = provider
        self.provider_name = getattr(provider, "name", None) or (
            os.environ.get("LLM_PROVIDER") or "anthropic")
        # Token accounting, so a run can report what its context actually cost.
        self.input_tokens = 0
        self.output_tokens = 0
        self.llm_calls = 0
        self.llm_failures = 0
        self.llm_cost_usd = 0.0
        self.llm_structured_mode = "none"   # last successful rung of the gateway ladder
        self.used_priors = 0                # explorers drawn from learned priors

    def propose(self, n: int, memory: MemoryLike) -> list[StrategyVariant]:
        if self.use_llm:
            return self._propose_llm(n, memory)
        return self._propose_heuristic(n, memory)

    # ----------------------------------------------------------------- heuristic
    def _propose_heuristic(self, n: int, memory: MemoryLike) -> list[StrategyVariant]:
        best = memory.best_params()
        get_priors = getattr(memory, "priors", None)
        box = get_priors() if callable(get_priors) else None
        variants: list[StrategyVariant] = []
        for k in range(n):
            exploit = best is not None and k < n - 1   # always keep >=1 explorer
            if exploit:
                params = self._perturb(best)
                rationale = "memory-guided: perturb best-so-far (exploit)"
                parent = memory.best_id()
            elif box is not None and self._rng.random() < 0.5:
                params = self._sample_box(box)
                rationale = "exploration: sampled from learned priors (procedural memory)"
                parent = None
                self.used_priors += 1
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

    def _sample_box(self, box: dict[str, tuple[float, float]]) -> dict[str, float]:
        """Sample inside the learned box, clipped to the declared space per parameter."""
        out: dict[str, float] = {}
        for k, (lo, hi) in PARAM_SPACE.items():
            blo, bhi = box.get(k, (lo, hi))
            blo, bhi = max(lo, min(blo, bhi)), min(hi, max(blo, bhi))
            out[k] = round(self._rng.uniform(blo, bhi), 3)
        return out

    def _perturb(self, base: dict[str, float]) -> dict[str, float]:
        out: dict[str, float] = {}
        for k, (lo, hi) in PARAM_SPACE.items():
            span = (hi - lo) * 0.15
            out[k] = round(min(hi, max(lo, base[k] + self._rng.uniform(-span, span))), 3)
        return out

    # ----------------------------------------------------------------------- LLM
    def _get_provider(self) -> Any:
        """Lazily build the gateway provider (imports pydantic + llm_gateway only here)."""
        if self._provider is None:
            from llm_gateway import get_provider

            self._provider = get_provider(self.provider_name, model=self._model_override)
            self.model = self._provider.model
            self.provider_name = self._provider.name
        return self._provider

    def _fallback(self, n: int, memory: MemoryLike, why: str) -> list[StrategyVariant]:
        # One batch failing must not lose the whole run; fall back for this batch only
        # and count it, so a degraded run never looks like a clean one.
        self.llm_failures += 1
        print(f"  ! LLM proposal failed ({why}); falling back to the heuristic "
              f"for this batch")
        return self._propose_heuristic(n, memory)

    def _propose_llm(self, n: int, memory: MemoryLike) -> list[StrategyVariant]:
        context = build_context(
            self.context_mode, memory.trials(), memory.best_params(), memory.best_score(),
            memory=memory,
        )
        user_turn = (
            context
            + f"\n\nPropose {n} new parameter sets to test next. Return JSON only."
        )

        try:
            from research_lab.schemas_llm import ProposalBatch

            provider = self._get_provider()
            resp = provider.complete(
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_turn}],
                max_tokens=LLM_MAX_TOKENS,
                schema=ProposalBatch,
                cache_system=True,
            )
        except Exception as e:  # noqa: BLE001 - no creds, API error, invalid JSON x2
            return self._fallback(n, memory, f"{type(e).__name__}: {e}")

        self.llm_calls += 1
        # Cache reads/writes count toward what the context actually cost to send.
        self.input_tokens += (resp.input_tokens + resp.cache_read_tokens
                              + resp.cache_write_tokens)
        self.output_tokens += resp.output_tokens
        self.llm_cost_usd += resp.cost_usd

        batch = resp.parsed
        proposals = list(getattr(batch, "variants", None) or [])
        if not proposals:
            return self._fallback(n, memory, "no usable proposals in the reply")
        self.llm_structured_mode = resp.structured_mode

        variants: list[StrategyVariant] = []
        for item in proposals[:n]:
            params = _clamp(item.params.model_dump(), self._sample())
            rationale = str(item.rationale).strip() or "llm proposal"
            self._counter += 1
            variants.append(
                StrategyVariant(
                    id=f"v{self._counter:03d}",
                    params=params,
                    rationale=f"llm[{self.context_mode}]: {rationale}",
                    parent_id=memory.best_id(),
                )
            )
        # The model may return fewer than asked; top up so every run tests the same
        # number of variants and the three constructions stay comparable.
        while len(variants) < n:
            variants.extend(self._propose_heuristic(1, memory))
        return variants


def _clamp(params: dict[str, Any], fallback: dict[str, float]) -> dict[str, float]:
    """Force a proposal into the declared space.

    The model is not trusted to respect the contract: a missing key takes the
    fallback sample, a non-numeric value is replaced, and anything out of range is
    clamped to the boundary. ``verify_variant`` still runs afterwards in the
    supervisor — this is belt and braces, because a hallucinated parameter should
    cost a clamp, not a crashed run.
    """
    out: dict[str, float] = {}
    for key, (lo, hi) in PARAM_SPACE.items():
        raw = params.get(key)
        try:
            val = float(raw)   # type: ignore[arg-type]
        except (TypeError, ValueError):
            val = fallback[key]
        out[key] = round(min(hi, max(lo, val)), 3)
    return out

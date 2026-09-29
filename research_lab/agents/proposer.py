"""Proposer agent — generates candidate strategy variants.

Two proposers behind one method. The deterministic path is a memory-guided heuristic
that runs offline with no API key: it exploits around the best variant found so far
and keeps one explorer per batch. The LLM path (``use_llm=True``) replaces that
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

The LLM path never bypasses verification: proposals come back as JSON, are clamped
into the declared parameter space, and still pass through ``verify_variant`` in the
supervisor. A model that hallucinates a ``lookback`` of 900 gets corrected by the
contract, not trusted. See ADR-0003.
"""

from __future__ import annotations

import json
import os
import random
from typing import Any

from research_lab.agents.context import build_context
from research_lab.memory import Memory
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


class LLMUnavailable(RuntimeError):
    """The LLM path was requested but cannot run (no key, or the SDK is missing)."""


class Proposer:
    """Propose strategy variants, deterministically or via an LLM.

    Args:
        seed: RNG seed for the deterministic path (and for the LLM path's fallback).
        use_llm: route proposals through Claude instead of the heuristic.
        model: model id for the LLM path.
        context_mode: which context construction to build — see ``agents/context.py``.
            Only meaningful when ``use_llm`` is set.
        start_counter: last variant number already issued, so a proposer rebuilt from a
            checkpoint (see ``research_lab/graph.py``) continues ``vNNN`` numbering.
    """

    def __init__(
        self,
        seed: int = 0,
        use_llm: bool = False,
        model: str = DEFAULT_LLM_MODEL,
        context_mode: str = "compacted",
        start_counter: int = 0,
    ) -> None:
        self._rng = random.Random(seed)
        self._counter = start_counter
        self.use_llm = use_llm
        self.model = model
        self.context_mode = context_mode
        self._client: Any = None
        # Token accounting, so a run can report what its context actually cost.
        self.input_tokens = 0
        self.output_tokens = 0
        self.llm_calls = 0
        self.llm_failures = 0

    def propose(self, n: int, memory: Memory) -> list[StrategyVariant]:
        if self.use_llm:
            return self._propose_llm(n, memory)
        return self._propose_heuristic(n, memory)

    # ----------------------------------------------------------------- heuristic
    def _propose_heuristic(self, n: int, memory: Memory) -> list[StrategyVariant]:
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

    # ----------------------------------------------------------------------- LLM
    def _get_client(self) -> Any:
        """Lazily build the Anthropic client. Raises if the path can't run.

        Deliberately loud rather than silently falling back to the heuristic: a run
        that *thinks* it measured an LLM proposer but quietly measured the heuristic
        is worse than a run that fails.
        """
        if self._client is None:
            if not os.environ.get("ANTHROPIC_API_KEY"):
                raise LLMUnavailable(
                    "use_llm=True but ANTHROPIC_API_KEY is not set. Run load_env() "
                    "or export the key; the deterministic path needs no key."
                )
            try:
                import anthropic
            except ImportError as e:   # pragma: no cover - depends on extras install
                raise LLMUnavailable(
                    "use_llm=True but the anthropic SDK is not installed. "
                    "Install the extra: pip install -e '.[llm]'"
                ) from e
            self._client = anthropic.Anthropic()
        return self._client

    def _propose_llm(self, n: int, memory: Memory) -> list[StrategyVariant]:
        client = self._get_client()
        context = build_context(
            self.context_mode, memory.trials(), memory.best_params(), memory.best_score()
        )
        user_turn = (
            context
            + f"\n\nPropose {n} new parameter sets to test next. Return JSON only."
        )

        try:
            resp = client.messages.create(
                model=self.model,
                max_tokens=LLM_MAX_TOKENS,
                system=[{"type": "text", "text": SYSTEM_PROMPT,
                         "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user_turn}],
            )
        except Exception as e:   # API error, rate limit, connection
            # One batch failing must not lose the whole run; fall back for this batch
            # only and count it, so the proof-bar table can report it honestly.
            self.llm_failures += 1
            print(f"  ! LLM proposal failed ({type(e).__name__}: {e}); "
                  f"falling back to the heuristic for this batch")
            return self._propose_heuristic(n, memory)

        self.llm_calls += 1
        usage = getattr(resp, "usage", None)
        if usage is not None:
            # Cache reads/writes count toward what the context actually cost to send.
            self.input_tokens += (
                getattr(usage, "input_tokens", 0)
                + (getattr(usage, "cache_creation_input_tokens", 0) or 0)
                + (getattr(usage, "cache_read_input_tokens", 0) or 0)
            )
            self.output_tokens += getattr(usage, "output_tokens", 0)

        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        proposals = _parse_proposals(text)
        if not proposals:
            self.llm_failures += 1
            print("  ! LLM returned no usable JSON; falling back to the heuristic "
                  "for this batch")
            return self._propose_heuristic(n, memory)

        variants: list[StrategyVariant] = []
        for item in proposals[:n]:
            params = _clamp(item.get("params", {}), self._sample())
            rationale = str(item.get("rationale", "")).strip() or "llm proposal"
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


def _parse_proposals(text: str) -> list[dict[str, Any]]:
    """Pull the variant list out of the model's reply.

    Tolerates a stray code fence or a sentence of preamble — the prompt asks for bare
    JSON, but parsing must not be the thing that breaks a measured run.
    """
    candidate = text
    if "```" in candidate:
        parts = candidate.split("```")
        for part in parts:
            cleaned = part.strip()
            if cleaned.startswith("json"):
                cleaned = cleaned[4:].strip()
            if cleaned.startswith("{"):
                candidate = cleaned
                break
    start, end = candidate.find("{"), candidate.rfind("}")
    if start == -1 or end == -1:
        return []
    try:
        data = json.loads(candidate[start:end + 1])
    except json.JSONDecodeError:
        return []
    variants = data.get("variants") if isinstance(data, dict) else None
    if not isinstance(variants, list):
        return []
    return [v for v in variants if isinstance(v, dict)]


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

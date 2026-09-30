"""Judge agent — an LLM-as-judge that can only *downgrade* a promotion candidate.

The evaluation ladder, in order, each rung only able to narrow what the previous let through:

    verify.py (deterministic)  →  Evaluator score (arithmetic)  →  Judge veto (LLM)  →  human gate

The arithmetic score stays primary: the judge never re-scores, never re-ranks, and never
upgrades. It reviews the rationale of the top-k ``promote?`` candidates against a fixed
rubric and returns a ``JudgeVerdict``; ``apply`` turns ``promote?`` into ``hold`` when the
rationale contradicts the metrics or the overfit risk is high. Everything else is left as
the Evaluator decided it. A judge failure (no key, provider error, invalid JSON twice, budget
exhausted) is an **abstention**: the verdict is unchanged and ``judge_failures`` is counted,
so a degraded review never looks like a clean one — and never blocks a run.

Like the LLM proposer, this module imports nothing optional at import time: ``llm_gateway``
and ``research_lab.schemas_llm`` (pydantic) are imported inside ``judge()`` only. The stdlib
arm (``run.py`` / ``supervisor.py``) imports this module only behind ``--judge``.
"""

from __future__ import annotations

import json
from dataclasses import asdict, replace
from typing import Any

from research_lab.agents.evaluator import MIN_TRADES, PROMOTE_MARGIN, score_result
from research_lab.budget import Budget
from research_lab.schemas import BacktestResult, Evaluation, RankedVariant, StrategyVariant
from synthetic_engine import PARAM_SPACE

JUDGE_MAX_TOKENS = 400
BOUNDARY_FRACTION = 0.02    # within 2% of a range's width of either end = "at the boundary"

_BOUNDS = "\n".join(f"    {k:<9} [{lo}, {hi}]" for k, (lo, hi) in PARAM_SPACE.items())

# Stable across every call and every run, so the provider can cache it; the variant under
# review goes in the user turn.
SYSTEM_PROMPT = f"""You are the judge in an autonomous quant-research loop. You review ONE
candidate strategy variant that the arithmetic evaluator has marked "promote?". You can only
veto it (downgrade to "hold"); you cannot promote anything, and a human still decides after you.

The strategy is a long-only mean-reversion rule backtested on a deterministic synthetic market.
Variants are scored as:

    score = total_return_pct - 0.5 * max_drawdown_pct + 40 * (win_rate - 0.5)

A variant is "promote?" when score >= baseline_score + {PROMOTE_MARGIN:g} and trades >= {MIN_TRADES}.

Declared parameter ranges (PARAM_SPACE):
{_BOUNDS}

Answer three questions:

1. rationale_consistent: does the rationale predict the direction the metrics actually moved
   versus the baseline? If it claims a change (e.g. "tighter stop reduces drawdown") and the
   metric moved the other way (drawdown rose), answer false. A rationale that makes no
   directional claim (e.g. "exploration: sampled fresh from the param space") has nothing to
   contradict: answer true.
2. overfit_risk: does the edge depend on a single parameter sitting at a range boundary
   (within {BOUNDARY_FRACTION:.0%} of the range width of either end)? Boundary-hugging means the
   optimum may lie outside the searched space: overfit_risk = "high". Also "high" when the trade
   count is too small to trust (at or barely above {MIN_TRADES}; fewer than ~10 trades is thin).
   "medium" for mild concerns, "low" otherwise.
3. Is the trade count large enough to trust? Fold this into overfit_risk as above.

Also give plausibility (1-5, how believable the edge is) and a note of at most 300 characters
naming the specific reason (e.g. "stop_pct at range floor").

Respond with ONLY a JSON object, no prose and no code fences:
{{"rationale_consistent": <bool>, "overfit_risk": "low"|"medium"|"high",
  "plausibility": <1-5>, "note": "<short reason>"}}"""


def _metrics(r: BacktestResult) -> dict[str, Any]:
    return {"return_pct": r.total_return_pct, "win_rate": r.win_rate,
            "max_drawdown_pct": r.max_drawdown_pct, "trades": r.trades}


def user_message(variant: StrategyVariant, result: BacktestResult, baseline: BacktestResult,
                 history_summary: str) -> str:
    """The per-candidate half of the prompt (the system prompt stays byte-stable)."""
    base, cand = _metrics(baseline), _metrics(result)
    delta = {k: round(cand[k] - base[k], 4) for k in cand}
    payload = {
        "variant_id": variant.id,
        "params": variant.params,
        "rationale": variant.rationale,
        "metrics": cand,
        "baseline_metrics": base,
        "change_vs_baseline": delta,
        "score": round(score_result(result), 2),
        "baseline_score": round(score_result(baseline), 2),
    }
    return (f"Run so far: {history_summary}\n\nCandidate under review:\n"
            f"{json.dumps(payload, indent=1)}\n\nReturn the JSON verdict only.")


def history_summary(n_tested: int, iterations: int, baseline_score: float,
                    n_promote: int) -> str:
    return (f"{n_tested} variants tested over {iterations} iterations; baseline score "
            f"{baseline_score:.1f}; {n_promote} reached 'promote?'.")


def is_veto(verdict: dict[str, Any] | None) -> bool:
    return verdict is not None and (not verdict.get("rationale_consistent", True)
                                    or verdict.get("overfit_risk") == "high")


def veto_reason(verdict: dict[str, Any]) -> str:
    """``overfit_risk=high: stop_pct at range floor`` / ``rationale_consistent=false: ...``."""
    why = ("rationale_consistent=false" if not verdict.get("rationale_consistent", True)
           else f"overfit_risk={verdict.get('overfit_risk')}")
    note = str(verdict.get("note") or "").strip()
    return f"{why}: {note}" if note else why


def veto_line(variant_id: str, verdict: dict[str, Any]) -> str:
    return f"judge: {variant_id} promote? → hold ({veto_reason(verdict)})"


def footer(calls: int, vetoes: int, failures: int, why: str | None = None) -> str:
    line = f"judge: {calls} calls · {vetoes} vetoes · {failures} abstained"
    return f"{line} (last: {why})" if failures and why else line


class Judge:
    """Review ``promote?`` candidates; veto (never upgrade).

    Args:
        provider: an ``llm_gateway`` provider. ``None`` builds one lazily from
            ``$LLM_PROVIDER`` on the first call (tests inject a ``FakeProvider``).
        top_k: how many of the highest-scoring ``promote?`` candidates to review.
        budget: the run's shared ``Budget``. Checked before each call (exhausted →
            abstain without calling) and charged after each response.
    """

    def __init__(self, provider: Any = None, top_k: int = 3, budget: Budget | None = None,
                 provider_name: str | None = None) -> None:
        self._provider = provider
        self.provider_name = provider_name
        self.top_k = top_k
        self.budget = budget
        self.judge_calls = 0
        self.judge_failures = 0
        self.judge_cost_usd = 0.0
        self.vetoes: list[tuple[str, dict[str, Any]]] = []   # (variant_id, verdict dict)
        self.last_error: str | None = None                   # why the last abstention happened

    def _get_provider(self) -> Any:
        if self._provider is None:
            from llm_gateway import get_provider
            self._provider = get_provider(self.provider_name)
        return self._provider

    def judge(self, variant: StrategyVariant, result: BacktestResult,
              baseline: BacktestResult, history_summary: str) -> Any:
        """One review → a ``JudgeVerdict``, or ``None`` (abstain; counted as a failure)."""
        if self.budget is not None and self.budget.exhausted():
            self.judge_failures += 1       # denied by the budget: abstain, never call
            self.last_error = f"budget exhausted ({self.budget.reason()})"
            return None
        try:
            from research_lab.schemas_llm import JudgeVerdict

            resp = self._get_provider().complete(
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message(
                    variant, result, baseline, history_summary)}],
                max_tokens=JUDGE_MAX_TOKENS,
                schema=JudgeVerdict,
                cache_system=True,
            )
        except Exception as e:  # noqa: BLE001 - no creds, API error, invalid JSON twice
            self.judge_failures += 1
            self.last_error = f"{type(e).__name__}: {str(e)[:120]}"
            return None
        self.judge_calls += 1
        self.judge_cost_usd += float(resp.cost_usd or 0.0)
        if self.budget is not None:
            self.budget.charge(resp.cost_usd)
        verdict = resp.parsed
        if not isinstance(verdict, JudgeVerdict):
            self.judge_failures += 1
            self.last_error = "reply did not parse as a JudgeVerdict"
            return None
        return verdict

    @staticmethod
    def apply(evaluation: Evaluation, verdict: Any) -> Evaluation:
        """The veto rule. Only ``promote?`` can change, and only to ``hold``."""
        if verdict is None or evaluation.verdict != "promote?":
            return evaluation
        vd = verdict.model_dump() if hasattr(verdict, "model_dump") else dict(verdict)
        if not is_veto(vd):
            return evaluation
        return replace(evaluation, verdict="hold", judge=vd,
                       notes=f"{evaluation.notes}; judge veto ({veto_reason(vd)})".lstrip("; "))

    def review(self, ranked: list[RankedVariant], baseline: BacktestResult,
               summary: str) -> list[RankedVariant]:
        """Judge the top-k ``promote?`` entries (by score) and return ``ranked`` with vetoes
        applied. Order and every other entry are untouched."""
        order = sorted(range(len(ranked)), key=lambda i: ranked[i].evaluation.score,
                       reverse=True)
        picked = [i for i in order if ranked[i].evaluation.verdict == "promote?"][:self.top_k]
        out = list(ranked)
        for i in picked:
            rv = ranked[i]
            verdict = self.judge(rv.variant, rv.result, baseline, summary)
            new_eval = self.apply(rv.evaluation, verdict)
            if new_eval is not rv.evaluation:
                self.vetoes.append((rv.variant.id, new_eval.judge or {}))
            out[i] = RankedVariant(rv.variant, rv.result, new_eval)
        return out


def ranked_dicts_review(judge: Judge, ranked: list[dict[str, Any]],
                        baseline: dict[str, Any], summary: str) -> list[dict[str, Any]]:
    """``Judge.review`` over the graph arm's JSON state (``RankedVariant`` dicts)."""
    rvs = [RankedVariant(StrategyVariant(**d["variant"]), BacktestResult(**d["result"]),
                         Evaluation(**d["evaluation"])) for d in ranked]
    reviewed = judge.review(rvs, BacktestResult(**baseline), summary)
    return [asdict(rv) for rv in reviewed]

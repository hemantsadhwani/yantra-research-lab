"""Context construction — three ways to spend the proposer's attention budget.

Day 6B's actual lesson. Once an LLM is in the loop there is a context window to
engineer, and the question stops being "what does the model know?" and becomes
"what is worth paying for?" Context is a finite resource with diminishing marginal
returns against the model's attention budget, so these are three deliberate points
on a cost/quality curve over the *same* underlying memory:

``everything``  every trial, every param set, every score. Maximum information,
                maximum tokens, and the signal the model needs is buried in the
                middle of a long list where attention is weakest.
``best_only``   just the best-so-far and the parameter space. The cheapest thing
                that could possibly work — and the deterministic proposer's own
                information diet, which makes it the honest control.
``compacted``   a short rolling summary: best-so-far, what the losing region looks
                like per parameter, and how many trials that summary stands for.
                Anthropic's "compaction" technique — spend tokens on the *shape* of
                the history rather than the history. When the memory store persists
                across runs (``SqliteMemory``), it also gets a *procedural* line (the
                box previous runs' top variants sat in) and up to 3 *recalled* trials
                from previous runs whose rationale reads like the current best.

``everything`` and ``best_only`` never look past the current run's trial log, so the
context study stays comparable whichever memory store backs the run.

Each builder returns a plain string that goes in the user turn. The system prompt
(the stable prefix, and the cacheable one) is identical across all three, so a token
delta between constructions is a delta in what the history costs, not prompt noise.
"""

from __future__ import annotations

from typing import Any

from research_lab.schemas import Trial
from synthetic_engine import PARAM_SPACE

CONSTRUCTIONS = ("everything", "best_only", "compacted")

# The compacted summary characterises the losing *region* from the worst third of
# trials. A fixed count would, early on, include every trial ever run — and "the
# losers ranged over the entire parameter space" is a true statement carrying no
# information. Taking a fraction keeps the summary contrastive as history grows.
_COMPACT_LOSER_FRACTION = 0.34
_COMPACT_LOSER_MIN = 3


def _param_space_block() -> str:
    lines = [f"  {k}: [{lo}, {hi}]" for k, (lo, hi) in PARAM_SPACE.items()]
    return "Parameter space (every value must sit inside its range):\n" + "\n".join(lines)


def _best_block(best_params: dict[str, float] | None, best_score: float | None) -> str:
    if best_params is None:
        return "No variant has been evaluated yet — this is the first batch."
    return f"Best so far: score {best_score:.1f} with params {_fmt(best_params)}"


def _fmt(params: dict[str, float]) -> str:
    return "{" + ", ".join(f"{k}={v:g}" for k, v in params.items()) + "}"


def build_everything(trials: list[Trial], best_params, best_score) -> str:
    """Dump the entire history. The expensive baseline the other two are judged against."""
    parts = [_param_space_block(), "", _best_block(best_params, best_score)]
    if trials:
        parts += ["", f"Full trial history ({len(trials)} trials, oldest first):"]
        parts += [
            f"  {t.variant_id}: {_fmt(t.params)} -> score {t.score:.1f} "
            f"({t.verdict}) · {t.rationale}"
            for t in trials
        ]
    return "\n".join(parts)


def build_best_only(trials: list[Trial], best_params, best_score) -> str:
    """Best-so-far plus the space. No history at all — the cheap control."""
    return "\n".join([_param_space_block(), "", _best_block(best_params, best_score)])


def _memory_blocks(trials: list[Trial], best_params, memory: Any) -> list[str]:
    """Procedural + semantic lines from a cross-run store; empty for plain ``Memory``."""
    out: list[str] = []
    get_priors = getattr(memory, "priors", None)
    box = get_priors() if callable(get_priors) else None
    if box:
        n_runs = getattr(memory, "prior_run_count", lambda: 0)()
        strategy = getattr(memory, "strategy", "") or "this strategy"
        ranges = ", ".join(f"{k} {lo:g}–{hi:g}" for k, (lo, hi) in box.items())
        plural = "s" if n_runs != 1 else ""
        out += ["", f"Across {n_runs} prior run{plural} on {strategy}, top variants had "
                    + f"{ranges}."]
    recall = getattr(memory, "recall_similar", None)
    if callable(recall):
        best_id = getattr(memory, "best_id", lambda: None)()
        query = next((t.rationale for t in trials if t.variant_id == best_id and t.rationale),
                     None) or "mean reversion"
        if best_params:
            query += " | " + " ".join(f"{k} {v:g}" for k, v in best_params.items())
        similar = recall(query, k=3, exclude_current_run=True)
        if similar:
            out += ["", "Similar trials from previous runs:"]
            out += [f"  {_fmt(t.params)} -> score {t.score:.1f} ({t.verdict}) · {t.rationale}"
                    for t in similar]
    return out


def build_compacted(trials: list[Trial], best_params, best_score, memory: Any = None) -> str:
    """A rolling summary: the peak, the losing region per parameter, and the trial count.

    The compression that matters is *per parameter*: knowing that every losing variant
    had ``lookback`` down at the bottom of its range is the one fact the model can act
    on, and it costs a line instead of a hundred.
    """
    parts = [_param_space_block(), "", _best_block(best_params, best_score)]
    parts += _memory_blocks(trials, best_params, memory)
    if not trials:
        return "\n".join(parts)

    k = max(_COMPACT_LOSER_MIN, int(len(trials) * _COMPACT_LOSER_FRACTION))
    losers = sorted(trials, key=lambda t: t.score)[:k]
    parts += ["", f"Summary of {len(trials)} trials so far:"]
    parts.append(f"  scores ranged {min(t.score for t in trials):.1f} "
                 f"to {max(t.score for t in trials):.1f}")
    promoted = sum(1 for t in trials if t.verdict == "promote?")
    rejected = sum(1 for t in trials if t.verdict == "reject")
    parts.append(f"  {promoted} promote-eligible, {rejected} rejected")
    if len(losers) < len(trials):
        parts.append(f"  the {len(losers)} weakest sat in these ranges:")
    else:
        parts.append(f"  all {len(losers)} so far sat in these ranges:")
    for key in PARAM_SPACE:
        vals = [t.params[key] for t in losers]
        parts.append(f"    {key}: {min(vals):g} to {max(vals):g}")
    return "\n".join(parts)


_BUILDERS = {
    "everything": build_everything,
    "best_only": build_best_only,
    "compacted": build_compacted,
}


def build_context(construction: str, trials: list[Trial], best_params, best_score,
                  memory: Any = None) -> str:
    """Dispatch to one of the three constructions by name.

    ``memory`` is only read by ``compacted`` (for cross-run priors and recall)."""
    try:
        builder = _BUILDERS[construction]
    except KeyError:
        raise ValueError(
            f"unknown context construction {construction!r}; choose from {list(CONSTRUCTIONS)}"
        ) from None
    if builder is build_compacted:
        return builder(trials, best_params, best_score, memory=memory)
    return builder(trials, best_params, best_score)

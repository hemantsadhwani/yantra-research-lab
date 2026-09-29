"""Day 6B proof bar — what does each context construction actually cost, and buy?

Runs the *same* loop three times against the same engine, the same baseline, the same
iteration budget and the same seed, changing exactly one thing: how much of memory's
trial history goes into the proposer's context window. Then prints one table.

    construction   tokens   best score   best Sharpe

The interesting result is not "which won" — it is the *shape* of the curve. If the
cheapest construction holds quality while tokens drop by an order of magnitude, that
is the whole context-engineering argument, measured on your own system instead of
quoted from a blog post. If it doesn't, that's a finding too: it says this loop's
history carries signal the model genuinely uses, and the expensive context earns its
tokens.

Usage:
    python -m research_lab.experiments.context_study
    python -m research_lab.experiments.context_study --iterations 3 --variants 4
    python -m research_lab.experiments.context_study --include-heuristic
    python -m research_lab.experiments.context_study --json results/context_study.json

Needs ANTHROPIC_API_KEY (see load_env.py) and the llm extra: pip install -e '.[llm]'
Costs real money — a few cents at the default budget. The deterministic control row
(--include-heuristic) costs nothing and is the honest "no LLM at all" comparison.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):   # cp1252 consoles choke on the box drawing
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from research_lab.agents.context import CONSTRUCTIONS
from research_lab.agents.proposer import DEFAULT_LLM_MODEL
from research_lab.supervisor import Supervisor
from synthetic_engine import DEFAULT_STRATEGY, list_strategies


@dataclass
class StudyRow:
    construction: str
    input_tokens: int
    output_tokens: int
    llm_calls: int
    llm_failures: int
    best_score: float
    best_sharpe: float
    best_return_pct: float
    best_params: dict
    wall_seconds: float


def run_one(
    construction: str,
    iterations: int,
    variants: int,
    seed: int,
    strategy: str,
    use_llm: bool = True,
) -> StudyRow:
    """One full research session under a single context construction."""
    sup = Supervisor(
        seed=seed,
        strategy=strategy,
        use_llm=use_llm,
        context_mode=construction,
        log=lambda m: print(f"    · {m}"),
    )
    t0 = time.monotonic()
    run = sup.run(iterations=iterations, variants_per_iter=variants)
    elapsed = time.monotonic() - t0

    best = run.best
    p = sup.proposer
    return StudyRow(
        construction=construction,
        input_tokens=p.input_tokens,
        output_tokens=p.output_tokens,
        llm_calls=p.llm_calls,
        llm_failures=p.llm_failures,
        best_score=best.evaluation.score if best else float("nan"),
        best_sharpe=best.result.sharpe if best else float("nan"),
        best_return_pct=best.result.total_return_pct if best else float("nan"),
        best_params=dict(best.variant.params) if best else {},
        wall_seconds=round(elapsed, 1),
    )


def _table(rows: list[StudyRow], baseline_score: float | None) -> str:
    w = 86
    out = ["", "=" * w,
           "  Day 6B · context construction study — same loop, same budget, same seed",
           "=" * w]
    if baseline_score is not None:
        out.append(f"  baseline score to beat: {baseline_score:.1f}")
        out.append("-" * w)
    out.append(f"  {'construction':<14}{'in tok':>9}{'out tok':>9}{'calls':>7}"
               f"{'score':>9}{'sharpe':>9}{'return':>9}{'secs':>8}")
    out.append("-" * w)
    for r in rows:
        fail = "*" if r.llm_failures else ""
        out.append(f"  {r.construction:<14}{r.input_tokens:>9,}{r.output_tokens:>9,}"
                   f"{str(r.llm_calls) + fail:>7}{r.best_score:>9.1f}{r.best_sharpe:>9.2f}"
                   f"{r.best_return_pct:>8.1f}%{r.wall_seconds:>8.1f}")
    out.append("-" * w)

    llm_rows = [r for r in rows if r.llm_calls]
    if len(llm_rows) > 1:
        cheapest = min(llm_rows, key=lambda r: r.input_tokens)
        dearest = max(llm_rows, key=lambda r: r.input_tokens)
        best_q = max(llm_rows, key=lambda r: r.best_score)
        if dearest.input_tokens:
            saving = 100 * (1 - cheapest.input_tokens / dearest.input_tokens)
            out.append(f"  cheapest context ({cheapest.construction}) used "
                       f"{saving:.0f}% fewer input tokens than {dearest.construction}")
        delta = cheapest.best_score - dearest.best_score
        out.append(f"  ...and scored {delta:+.1f} against it "
                   f"(best overall: {best_q.construction} at {best_q.best_score:.1f})")
    if any(r.llm_failures for r in rows):
        out.append("  * at least one batch fell back to the heuristic — see the log above")
    out.append("=" * w)
    out.append("")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description="Measure three context constructions.")
    ap.add_argument("--iterations", type=int, default=3)
    ap.add_argument("--variants", type=int, default=4)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--strategy", default=DEFAULT_STRATEGY, choices=list_strategies())
    ap.add_argument("--constructions", nargs="*", default=list(CONSTRUCTIONS),
                    choices=list(CONSTRUCTIONS))
    ap.add_argument("--include-heuristic", action="store_true",
                    help="also run the deterministic proposer as a zero-token control")
    ap.add_argument("--json", dest="json_out", default=None,
                    help="write the raw rows to this path")
    args = ap.parse_args()

    try:
        from load_env import load_env
        load_env()
    except Exception:   # running outside the repo root is not fatal
        pass

    rows: list[StudyRow] = []
    for construction in args.constructions:
        print(f"\n  ── {construction} ──")
        rows.append(run_one(construction, args.iterations, args.variants,
                            args.seed, args.strategy))

    if args.include_heuristic:
        print("\n  ── deterministic (control, no LLM) ──")
        rows.append(run_one("heuristic", args.iterations, args.variants,
                            args.seed, args.strategy, use_llm=False))

    print(_table(rows, None))

    if args.json_out:
        path = Path(args.json_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "strategy": args.strategy,
            "iterations": args.iterations,
            "variants_per_iter": args.variants,
            "seed": args.seed,
            "model": DEFAULT_LLM_MODEL,
            "rows": [asdict(r) for r in rows],
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"  wrote {path}")


if __name__ == "__main__":
    main()

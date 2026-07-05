"""CLI entrypoint — run one autonomous research session and print the report.

    python -m research_lab.run                 # defaults: 4 iterations x 5 variants
    python -m research_lab.run --iterations 6 --variants 6 --seed 7
    python -m research_lab.run --strategy nifty-expiry
"""

from __future__ import annotations

import argparse

from research_lab.schemas import RunResult
from research_lab.supervisor import Supervisor
from synthetic_engine import DEFAULT_STRATEGY, list_strategies


def _report(run: RunResult, strategy: str) -> str:
    lines: list[str] = []
    b = run.baseline
    lines.append("")
    lines.append("=" * 68)
    lines.append("  yantra-research-lab · autonomous strategy research (synthetic)")
    lines.append(f"  strategy: {strategy}  (synthetic stand-in · real logic is private)")
    lines.append("=" * 68)
    lines.append(f"  iterations: {run.iterations}   variants tested: {run.variants_tested}")
    lines.append(f"  baseline:   return {b.total_return_pct:+8.1f}%   "
                 f"win {b.win_rate:.0%}   dd {b.max_drawdown_pct:.1f}%   trades {b.trades}")
    lines.append("-" * 68)
    lines.append(f"  {'rank':<5}{'variant':<9}{'return':>9}{'win':>6}{'dd':>7}"
                 f"{'score':>8}  verdict")
    lines.append("-" * 68)
    for i, rv in enumerate(run.ranked[:8], start=1):
        r, e = rv.result, rv.evaluation
        lines.append(f"  {i:<5}{rv.variant.id:<9}{r.total_return_pct:>8.1f}%"
                     f"{r.win_rate:>6.0%}{r.max_drawdown_pct:>6.1f}%"
                     f"{e.score:>8.1f}  {e.verdict}")
    lines.append("-" * 68)
    best = run.best
    if best:
        lift = best.evaluation.score - (b.total_return_pct - 0.5 * b.max_drawdown_pct
                                        + 40.0 * (b.win_rate - 0.5))
        lines.append(f"  BEST: {best.variant.id}  ({best.variant.rationale})")
        lines.append(f"        params: {best.variant.params}")
        lines.append(f"        beats baseline by {lift:+.1f} score points → "
                     f"verdict '{best.evaluation.verdict}'")
        lines.append("  ⏸  HUMAN-IN-THE-LOOP: nothing is promoted autonomously — "
                     "a human approves 'promote?'.")
    lines.append("=" * 68)
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Run one autonomous research session.")
    ap.add_argument("--iterations", type=int, default=4)
    ap.add_argument("--variants", type=int, default=5)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--strategy", default=DEFAULT_STRATEGY, choices=list_strategies(),
                    help="which (synthetic) strategy engine the agent loop drives")
    args = ap.parse_args()

    supervisor = Supervisor(seed=args.seed, strategy=args.strategy, log=lambda m: print(f"  · {m}"))
    run = supervisor.run(iterations=args.iterations, variants_per_iter=args.variants)
    print(_report(run, args.strategy))


if __name__ == "__main__":
    main()

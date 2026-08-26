"""CI eval-gate: the agent loop must still discover a variant that beats the baseline.

Exits non-zero on regression so CI blocks the dev→prod promotion. This is the
backtest-parity / eval-gate discipline applied to the pipeline itself: never ship a
change that makes the research loop worse. Extend with RAG-golden + red-team leak checks
as those tiers land.
"""

from __future__ import annotations

import sys

# Windows consoles default to cp1252 and mangle the arrow in the verdict line.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from research_lab.agents.evaluator import score_result
from research_lab.supervisor import Supervisor


def main() -> int:
    run = Supervisor(seed=3).run(iterations=5, variants_per_iter=6)
    best = run.best
    baseline_score = score_result(run.baseline)
    if best is None or best.evaluation.score <= baseline_score or best.evaluation.verdict != "promote?":
        got = f"{best.evaluation.score:.1f}" if best else "none"
        print(f"EVAL-GATE FAIL · best={got} baseline={baseline_score:.1f}")
        return 1
    print(f"EVAL-GATE PASS · best {best.variant.id} score {best.evaluation.score:.1f} "
          f"> baseline {baseline_score:.1f} ({best.evaluation.verdict})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

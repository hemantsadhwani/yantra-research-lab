"""Generate the cached Research-Lab run the public site renders.

Runs the existing deterministic supervisor loop (no API key, no LLM calls) and writes a JSON
snapshot the frontend reads statically — so the Research Lab screen costs $0 per visitor.
Re-run any time to refresh:

    python scripts/generate_run.py                 # -> scripts/data/run.json
    python scripts/generate_run.py <out_path>      # custom output

Deterministic given the seed, so the committed run.json is reproducible.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Make the repo root importable no matter where this script is invoked from.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from research_lab.agents.evaluator import score_result  # noqa: E402
from research_lab.supervisor import Supervisor  # noqa: E402

SEED = 3
ITERATIONS = 5
VARIANTS_PER_ITER = 6


def build() -> dict:
    run = Supervisor(seed=SEED).run(iterations=ITERATIONS, variants_per_iter=VARIANTS_PER_ITER)
    baseline_score = score_result(run.baseline)

    def rv(rank, r):
        return {
            "rank": rank,
            "variant_id": r.variant.id,
            "parent_id": r.variant.parent_id,
            "params": {k: round(v, 3) for k, v in r.variant.params.items()},
            "rationale": r.variant.rationale,
            "total_return_pct": r.result.total_return_pct,
            "win_rate": r.result.win_rate,
            "max_drawdown_pct": r.result.max_drawdown_pct,
            "sharpe": r.result.sharpe,
            "trades": r.result.trades,
            "score": round(r.evaluation.score, 1),
            "verdict": r.evaluation.verdict,
        }

    ranked = [rv(i, r) for i, r in enumerate(run.ranked, start=1)]
    return {
        "_note": (
            "Cached deterministic run of the PUBLIC synthetic engine. Regenerate with "
            "`python scripts/generate_run.py`. No LLM calls, no real trading data."
        ),
        "strategy": "synthetic-meanrev",
        "run_id": 42,
        "seed": SEED,
        "iterations": run.iterations,
        "variants_per_iter": VARIANTS_PER_ITER,
        "variants_tested": run.variants_tested,
        "baseline": {
            "total_return_pct": run.baseline.total_return_pct,
            "win_rate": run.baseline.win_rate,
            "max_drawdown_pct": run.baseline.max_drawdown_pct,
            "trades": run.baseline.trades,
            "score": round(baseline_score, 1),
        },
        "ranked": ranked,
        "best_variant_id": ranked[0]["variant_id"] if ranked else None,
        "hitl": (
            "Nothing is promoted autonomously — the top variant is surfaced as 'promote?' "
            "for a human approval gate."
        ),
    }


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent / "data" / "run.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    data = build()
    out.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"wrote {out} · {len(data['ranked'])} variants · "
          f"baseline score {data['baseline']['score']} · best {data['best_variant_id']}")


if __name__ == "__main__":
    main()

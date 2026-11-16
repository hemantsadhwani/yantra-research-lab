"""Planted-edge benchmark: does the research process promote real edges and reject noise?

    python -m eval.planted_benchmark            # arms: naive, protocol  -> results/planted_benchmark_<date>.json

20 synthetic markets with a known answer (quant_engine/synthetic.py):
  10 with a planted edge (5 trend, 5 mean-reversion)  -> the right verdict is PROMOTE
  10 pure noise (same volatility process, no structure) -> the right verdict is REJECT
Each market comes with an idea in plain words (a template family), as a researcher would bring.

Arms:
  naive     grid search over the idea's templates; promote the best in-sample result if its
            Sharpe >= 0.6 (what an unguarded optimisation does)
  protocol  same grid, judged by walk-forward + a locked 2-year holdout (quant_engine.validate)
  agents    (added with the agent system) the multi-agent researcher under the same protocol

Edge strengths and thresholds were calibrated on seeds 1000-1019; this benchmark uses seeds
1-20, which calibration never saw. Report the numbers as produced, per arm.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
import time
from pathlib import Path

from quant_engine import synthetic
from quant_engine import validate as v
from quant_engine.data import dataset_card

IDEAS = {
    "trend": ("Ride sustained trends", ["ema_cross", "donchian_breakout"]),
    "meanrev": ("Buy short-term oversold dips", ["rsi_reversion", "bollinger_reversion"]),
}
CASES = (
    [("trend", s) for s in range(1, 6)]
    + [("meanrev", s) for s in range(6, 11)]
    + [("noise", s) for s in range(11, 21)]
)
PROTO = v.Protocol(naive_sharpe_min=0.6)


def run_case(kind: str, seed: int) -> dict:
    b = synthetic.generate(kind, seed)
    idea_kind = kind if kind != "noise" else ("trend" if seed % 2 else "meanrev")
    idea, templates = IDEAS[idea_kind]
    t0 = time.perf_counter()
    cands = [c for t in templates for c in v.evaluate_all(b, t, v.grid(t), PROTO.cost_bps)]
    naive, proto = v.naive(b, cands, PROTO), v.protocol(b, cands, PROTO)
    return {
        "seed": seed, "market": kind, "truth": "edge" if kind != "noise" else "no_edge",
        "idea": idea, "templates": templates, "dataset": dataset_card(b, f"synthetic {kind} seed {seed}"),
        "naive": {"promote": naive["promote"], "in_sample_sharpe": naive["in_sample"]["sharpe"],
                  "template": naive["template"], "trials": naive["trials"]},
        "protocol": {"promote": proto["promote"], "reason": proto["reason"],
                     "oos_sharpe": proto["walk_forward"]["oos_sharpe"],
                     "positive_folds": proto["walk_forward"]["positive_folds"],
                     "holdout_sharpe": proto.get("holdout", {}).get("sharpe"),
                     "trials": proto["trials"]},
        "seconds": round(time.perf_counter() - t0, 2),
    }


def summarise(cases: list[dict], arm: str) -> dict:
    edge = [c for c in cases if c["truth"] == "edge"]
    noise = [c for c in cases if c["truth"] == "no_edge"]
    return {
        "edges_recovered": f"{sum(c[arm]['promote'] for c in edge)}/{len(edge)}",
        "noise_promoted": f"{sum(c[arm]['promote'] for c in noise)}/{len(noise)}",
        "trials": sum(c[arm]["trials"] for c in cases),
    }


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    cases = []
    for kind, seed in CASES:
        c = run_case(kind, seed)
        cases.append(c)
        print(f"  seed {seed:>2} {kind:<8} naive {'PROMOTE' if c['naive']['promote'] else 'reject ':<7}"
              f"  protocol {'PROMOTE' if c['protocol']['promote'] else 'reject ':<7} ({c['protocol']['reason']})")
    out = {
        "what": "Planted-edge benchmark: 10 markets with a real edge, 10 of pure noise; seeds 1-20 "
                "(calibration used 1000-1019).",
        "date": dt.date.today().isoformat(),
        "protocol": PROTO.__dict__,
        "summary": {arm: summarise(cases, arm) for arm in ("naive", "protocol")},
        "cases": cases,
    }
    path = Path("results") / f"planted_benchmark_{out['date']}.json"
    path.write_text(json.dumps(out, indent=1), encoding="utf-8")
    for arm, s in out["summary"].items():
        print(f"{arm:<9} edges recovered {s['edges_recovered']}, noise promoted {s['noise_promoted']}, "
              f"{s['trials']} trials")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

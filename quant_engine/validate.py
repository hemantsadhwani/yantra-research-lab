"""The validation protocol: what separates a research result from a curve fit.

    |---------------- development ----------------|-- holdout --|
    | train | test1 | test2 | test3 | test4 | test5 |   locked    |

* Walk-forward: for each test block, the best parameters are chosen on everything BEFORE it
  (expanding window) and judged only on the block. The stitched test blocks are the
  out-of-sample (OOS) record.
* Holdout: the last ``holdout_days`` bars are opened once, at the end, for the final choice.
* Trials are counted: every parameter set evaluated is one trial, recorded with the verdict.

``naive`` is what an unguarded grid search does: pick the best in-sample result on all the
development data and promote it if it looks good. The benchmark compares the two.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field

from quant_engine import backtest as bt
from quant_engine.data import Bars
from quant_engine.templates import TEMPLATES, positions


@dataclass(frozen=True)
class Protocol:
    holdout_days: int = 504          # about two years
    folds: int = 5                   # walk-forward test blocks after the first training block
    oos_sharpe_min: float = 0.4
    positive_folds_min: float = 0.6  # share of test blocks with a positive return
    holdout_sharpe_min: float = 0.2
    naive_sharpe_min: float = 0.8
    cost_bps: float = 5.0


@dataclass
class Candidate:
    template: str
    params: dict
    result: bt.Result = field(repr=False)


def grid(template: str, with_filters: bool = True) -> list[dict]:
    space = TEMPLATES[template].full_space(with_filters)
    keys = list(space)
    return [dict(zip(keys, vals, strict=True)) for vals in itertools.product(*(space[k] for k in keys))]


def evaluate_all(b: Bars, template: str, param_sets: list[dict], cost_bps: float) -> list[Candidate]:
    return [Candidate(template, p, bt.run(b, positions(b, template, p), cost_bps)) for p in param_sets]


def _best(cands: list[Candidate], a: int, z: int) -> Candidate:
    return max(cands, key=lambda c: bt.sharpe(c.result.returns[a:z]))


def naive(b: Bars, cands: list[Candidate], proto: Protocol) -> dict:
    dev_end = len(b) - proto.holdout_days
    best = _best(cands, 1, dev_end)
    m = bt.metrics(best.result, 1, dev_end)
    return {"arm": "naive", "promote": m["sharpe"] >= proto.naive_sharpe_min,
            "template": best.template, "params": best.params, "in_sample": m, "trials": len(cands)}


def walk_forward(b: Bars, cands: list[Candidate], proto: Protocol) -> dict:
    dev_end = len(b) - proto.holdout_days
    block = dev_end // (proto.folds + 1)
    oos: list[float] = []
    folds = []
    for k in range(1, proto.folds + 1):
        a, z = k * block, (k + 1) * block if k < proto.folds else dev_end
        pick = _best(cands, 1, a)
        m = bt.metrics(pick.result, a, z)
        oos += pick.result.returns[a:z]
        folds.append({"test": [b.date[a], b.date[z - 1]], "params": pick.params, **m})
    positive = sum(1 for f in folds if f["total_return_pct"] > 0)
    oos_sharpe = round(bt.sharpe(oos), 3)
    passed = oos_sharpe >= proto.oos_sharpe_min and positive >= math.ceil(proto.positive_folds_min * proto.folds)
    return {"oos_sharpe": oos_sharpe, "positive_folds": positive, "folds": folds, "passed": passed}


def holdout(b: Bars, cands: list[Candidate], proto: Protocol) -> dict:
    """Opened once: the parameters chosen on all development data, judged on the holdout."""
    dev_end = len(b) - proto.holdout_days
    final = _best(cands, 1, dev_end)
    m = bt.metrics(final.result, dev_end, len(b))
    return {"params": final.params, **m, "passed": m["sharpe"] >= proto.holdout_sharpe_min}


def protocol(b: Bars, cands: list[Candidate], proto: Protocol) -> dict:
    wf = walk_forward(b, cands, proto)
    out = {"arm": "protocol", "trials": len(cands), "walk_forward": wf}
    if not wf["passed"]:
        return {**out, "promote": False, "reason": "failed walk-forward"}
    ho = holdout(b, cands, proto)
    return {**out, "holdout": ho, "promote": ho["passed"],
            "reason": "passed" if ho["passed"] else "failed holdout"}

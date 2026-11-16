"""The engine-side tools the agents call. Code, not models: every number comes from here.

These have the shape of MCP tools (plain JSON in, plain JSON out) so a private engine can serve
the same names behind its own server. The ledger is the run's memory and its audit trail: every
parameter set evaluated is a counted trial, every walk-forward evaluation a counted look, and the
holdout is opened by ``open_holdout`` only, once.
"""

from __future__ import annotations

import itertools
import math
from functools import lru_cache

from quant_engine import backtest as bt
from quant_engine import synthetic
from quant_engine import validate as v
from quant_engine.data import Bars, dataset_card
from quant_engine.templates import FILTER_SPACE, TEMPLATES

PROTO = v.Protocol(naive_sharpe_min=0.6)
ROUND_TRIAL_CAP = 150
LOOK_PENALTY = 0.1


def required_oos_sharpe(looks: int) -> float:
    """The walk-forward bar rises with every look: an agent that adapts to validation results
    turns them into in-sample data (a deflated-Sharpe-style haircut, fixed from first
    principles, not tuned): 0.4 at 1 look, 0.6 at 4, 0.7 at 8."""
    return round(PROTO.oos_sharpe_min + LOOK_PENALTY * math.log2(max(1, looks)), 3)


# ---------- data ----------
@lru_cache(maxsize=32)
def load(source: str) -> Bars:
    """``NIFTY50+VIX`` (public daily data) or ``synthetic:<kind>:<seed>``."""
    if source == "NIFTY50+VIX":
        from quant_engine.market_data import nifty_with_vix
        return nifty_with_vix()[0]
    if source.startswith("synthetic:"):
        _, kind, seed = source.split(":")
        return synthetic.generate(kind, int(seed))
    raise ValueError(f"unknown source {source!r}")


def card(source: str) -> dict:
    return dataset_card(load(source), source)


# ---------- experiments ----------
def catalogue() -> dict:
    """What the planner and researcher may choose from."""
    return {name: {"style": t.style, "description": t.description, "params": t.space,
                   "filters": FILTER_SPACE} for name, t in TEMPLATES.items()}


def clamp(template: str, params: dict[str, list[float]]) -> tuple[dict[str, list[float]], list[str]]:
    """Keep only catalogue values; unspecified template params take the full catalogue list,
    unspecified filters stay off. Returns the sub-space and what was dropped (shown to agents)."""
    if template not in TEMPLATES:
        raise ValueError(f"unknown template {template!r}")
    space = TEMPLATES[template].full_space()
    sub, dropped = {}, []
    for k, allowed in space.items():
        asked = params.get(k)
        if asked is None:
            sub[k] = list(allowed) if k in TEMPLATES[template].space else [0]
            continue
        keep = [x for x in allowed if any(math.isclose(x, a) for a in asked)]
        dropped += [f"{k}={a}" for a in asked if not any(math.isclose(a, x) for x in allowed)]
        sub[k] = keep or ([0] if k in FILTER_SPACE else list(allowed))
    dropped += [f"{k} (not a parameter)" for k in params if k not in space]
    return sub, dropped


def n_trials(sub: dict[str, list[float]]) -> int:
    return math.prod(len(v_) for v_ in sub.values())


def _cands(b: Bars, template: str, sub: dict[str, list[float]]) -> list[v.Candidate]:
    keys = list(sub)
    psets = [dict(zip(keys, vals, strict=True)) for vals in itertools.product(*(sub[k] for k in keys))]
    return v.evaluate_all(b, template, psets, PROTO.cost_bps)


def _bh(b: Bars) -> list[float]:
    return [0.0] + [b.close[i] / b.close[i - 1] - 1 for i in range(1, len(b))]


def run_family(source: str, template: str, sub: dict[str, list[float]], fid: str, round_no: int) -> dict:
    """Walk-forward one family (best parameters re-chosen before every test block)."""
    b = load(source)
    cands = _cands(b, template, sub)
    wf = v.walk_forward(b, cands, PROTO)
    dev_end = len(b) - PROTO.holdout_days
    best = max(cands, key=lambda c: bt.sharpe(c.result.returns[1:dev_end]))
    bh = _bh(b)
    block = dev_end // (PROTO.folds + 1)
    bh_oos = bt.sharpe(bh[block:dev_end])
    return {
        "id": fid, "round": round_no, "template": template, "space": sub, "trials": len(cands),
        "in_sample_sharpe": round(bt.sharpe(best.result.returns[1:dev_end]), 3),
        "best_params": best.params,
        "oos_sharpe": wf["oos_sharpe"], "positive_folds": wf["positive_folds"],
        "passed_walk_forward": wf["passed"], "buy_hold_oos_sharpe": round(bh_oos, 3),
        "folds": [{"test": f["test"], "sharpe": f["sharpe"], "return_pct": f["total_return_pct"]}
                  for f in wf["folds"]],
    }


# ---------- diagnostics (dev data only; the holdout is never touched) ----------
def _dev(source: str) -> tuple[Bars, int]:
    b = load(source)
    return b, len(b) - PROTO.holdout_days


def diagnostics(source: str, family: dict) -> dict:
    """Where the family's best parameters make and lose money: by VIX level, by trend state,
    and by year."""
    from quant_engine import indicators as ind
    from quant_engine.templates import positions
    b, dev_end = _dev(source)
    res = bt.run(b, positions(b, family["template"], family["best_params"]), PROTO.cost_bps)
    ema200 = ind.ema(b.close, 200)
    buckets: dict[str, list[float]] = {}
    years: dict[str, float] = {}
    for t in range(1, dev_end):
        r = res.returns[t]
        if b.vix is not None:
            vx = b.vix[t - 1]
            k = "vix<15" if vx < 15 else "vix15-25" if vx <= 25 else "vix>25"
            buckets.setdefault(k, []).append(r)
        e = ema200[t - 1]
        if e is not None:
            buckets.setdefault("uptrend" if b.close[t - 1] > e else "downtrend", []).append(r)
        y = b.date[t][:4]
        years[y] = years.get(y, 0.0) + r
    return {
        "family": family["id"],
        "by_regime": {k: {"days": len(x), "sharpe": round(bt.sharpe(x), 2),
                          "return_pct": round(100 * sum(x), 1)} for k, x in buckets.items()},
        "by_year_return_pct": {y: round(100 * x, 1) for y, x in sorted(years.items())},
    }


def neighbourhood(source: str, family: dict) -> dict:
    """Robustness: dev Sharpe of the best parameters' grid neighbours (one step per parameter).
    A real edge sits on a plateau; a curve fit sits on a spike."""
    from quant_engine.templates import positions
    b, dev_end = _dev(source)
    space = TEMPLATES[family["template"]].full_space()
    centre = family["best_params"]
    out = []
    for k, vals in space.items():
        if centre.get(k) not in vals:
            continue
        i = vals.index(centre[k])
        for j in (i - 1, i + 1):
            if 0 <= j < len(vals):
                p = {**centre, k: vals[j]}
                res = bt.run(b, positions(b, family["template"], p), PROTO.cost_bps)
                out.append(bt.sharpe(res.returns[1:dev_end]))
    c = family["in_sample_sharpe"]
    out.sort()
    return {"family": family["id"], "centre_sharpe": c, "neighbours": len(out),
            "neighbour_median_sharpe": round(out[len(out) // 2], 3) if out else None,
            "neighbour_min_sharpe": round(out[0], 3) if out else None,
            "share_within_70pct": round(sum(1 for x in out if c > 0 and x >= 0.7 * c) / len(out), 2) if out else None}


# ---------- the holdout: opened once, by the supervisor ----------
def open_holdout(source: str, family: dict) -> dict:
    b = load(source)
    cands = _cands(b, family["template"], family["space"])
    ho = v.holdout(b, cands, PROTO)
    dev_end = len(b) - PROTO.holdout_days
    return {"family": family["id"], "params": ho["params"], "sharpe": ho["sharpe"],
            "return_pct": ho["total_return_pct"], "max_drawdown_pct": ho["max_drawdown_pct"],
            "trades": ho["trades"], "passed": ho["passed"],
            "buy_hold_sharpe": round(bt.sharpe(_bh(b)[dev_end:]), 3),
            "window": [b.date[dev_end], b.date[-1]]}

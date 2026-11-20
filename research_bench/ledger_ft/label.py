"""Code labels every researcher proposal from the walk-forward results it produced. No model judges.

A study trace (written by ``teacher.run_study``) holds the ledger's families, the final verdict,
the market's known truth (synthetic: planted edge or pure noise) and each model-written proposal.
A proposal at round r is a WIN only if the study's final verdict is right AND:

  edge market   (a) a family run from this proposal passed walk-forward at the bar for the looks
                    counted after round r (OOS Sharpe >= 0.4 + 0.1*log2(looks), >= 4/6 blocks), or
                (b) it stopped with no new trials when an earlier family already cleared the bar.
  noise market  it stopped with no new trials. Running trials on noise is never a win, even if
                they all fail, and a noise family that passes walk-forward is a false discovery.

Everything else is a LOSS with a reason. Labels are a pure function of the trace (tested).
"""

from __future__ import annotations

from research_bench import tools
from research_bench.ledger_ft.seeds import require_calibration

LABEL_RULE = "v1: right verdict AND (edge: new family clears the raised bar, or efficient stop; noise: stop, 0 trials)"


def _clears(f: dict, looks: int) -> bool:
    return bool(f["passed_walk_forward"]) and tools.score(f) >= tools.required_oos_sharpe(looks)


def label_proposal(prop: dict, trace: dict) -> tuple[str, str]:
    r = prop["round"]
    fams = trace["families"]
    edge = trace["truth"] == "edge"
    if bool(trace["promote"]) != edge:
        return "loss", "study verdict wrong"
    new = [f for f in fams if f["round"] == r]
    prior = [f for f in fams if f["round"] < r]
    out = prop["output"]
    stopped = bool(out.get("stop")) and not new
    if not edge:
        if stopped:
            return "win", "noise: stopped with no new trials"
        return "loss", "noise: spent trials" if new else "noise: no trials but did not stop (refused by code)"
    looks_after = len(prior) + len(new)
    if any(_clears(f, looks_after) for f in new):
        return "win", "edge: a new family cleared walk-forward at the raised bar"
    if stopped and any(_clears(f, len(prior)) for f in prior):
        return "win", "edge: stopped once an earlier family cleared the bar"
    if not new:
        return "loss", "edge: no new family (stopped early or refused by code)"
    return "loss", "edge: new families did not clear the bar"


def label_trace(trace: dict) -> list[dict]:
    """One row per model-written proposal: id, seed, round, label, reason."""
    require_calibration(int(trace["seed"]))
    return [{"id": f"{trace['seed']}-r{p['round']}", "seed": trace["seed"], "kind": trace["kind"],
             "round": p["round"], **dict(zip(("label", "reason"), label_proposal(p, trace), strict=True))}
            for p in trace["proposals"]]

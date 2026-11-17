"""Planted-edge benchmark: does the research process promote real edges and reject noise?

    python -m eval.planted_benchmark                    # arms: naive, protocol
    python -m eval.planted_benchmark --agents offline   # + the bench with rule-based agents (no model)
    AWS_PROFILE=agentic python -m eval.planted_benchmark --agents llm   # + the bench with LLM agents
    -> results/planted_benchmark_<date>[_agents-<x>].json

20 synthetic markets with a known answer (quant_engine/synthetic.py):
  10 with a planted edge (5 trend, 5 mean-reversion)  -> the right verdict is PROMOTE
  10 pure noise (same volatility process, no structure) -> the right verdict is REJECT
Each market comes with an idea in plain words (a template family), as a researcher would bring.

Arms:
  naive     grid search over the idea's templates; promote the best in-sample result if its
            Sharpe >= 0.6 (what an unguarded optimisation does)
  protocol  same grid, judged by walk-forward + a locked 2-year holdout (quant_engine.validate)
  agents    research_bench in benchmark mode (no questions, no human): given only the idea text,
            the agents choose templates, filters and rounds; code runs the same walk-forward and
            holdout, with the bar raised per look (research_bench.tools.required_oos_sharpe)

Edge strengths and thresholds were calibrated on seeds 1000-1019; this benchmark uses seeds
1-20, which calibration never saw (see DISCLOSURE for the agents arm). Report the numbers as
produced, per arm.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
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
DISCLOSURE = (
    "The looks penalty (required OOS Sharpe = 0.4 + 0.1*log2(looks)) was added after an early "
    "smoke test of the adaptive search, using rule-based agents, promoted the noise market at "
    "benchmark seed 12. The penalty was set from first principles, not tuned; all later agent "
    "tuning used calibration seeds 1000+. Seed 12 is therefore not fully unseen for the agents arm. "
    "LLM agents v1 (results/planted_benchmark_2026-11-16_agents-llm.json) recovered 6/10 edges, "
    "0/10 noise; its misses (seeds 7-9) came from narrow first looks (textbook RSI 14) and an early "
    "critic stop. v2 makes round 1 a code-run baseline (each planned template's full grid). v2 was "
    "checked on calibration seeds 1000-1019 (9/10 edges, 0/10 noise, 1,552 trials) before ONE re-run "
    "on seeds 1-20 (file tag v2). The v2 change was prompted by v1's benchmark failures; both are kept."
)


def idea_for(kind: str, seed: int) -> tuple[str, list[str]]:
    return IDEAS[kind if kind != "noise" else ("trend" if seed % 2 else "meanrev")]


def run_case(kind: str, seed: int) -> dict:
    b = synthetic.generate(kind, seed)
    idea, templates = idea_for(kind, seed)
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


def agents_case(kind: str, seed: int, which: str, models: str = "mixed") -> dict:
    from research_bench.agents import MODEL_SETS, LLMAgents, OfflineAgents
    from research_bench.graph import build, new_state
    idea, _ = idea_for(kind, seed)
    t0 = time.perf_counter()
    try:
        agents = LLMAgents(role_models=dict(MODEL_SETS[models])) if which == "llm" else OfflineAgents()
        out = build(agents).invoke(
            new_state(idea, f"synthetic:{kind}:{seed}", mode="benchmark", budget_usd=0.05),
            {"recursion_limit": 80})
    except Exception as e:  # noqa: BLE001 - a failed study counts as a reject, recorded as an error
        return {"promote": False, "error": f"{type(e).__name__}: {e}"[:300], "trials": 0,
                "seconds": round(time.perf_counter() - t0, 1)}
    led, verdict = out["ledger"], out["verdict"]
    return {"promote": verdict["decision"] == "promote?", "reason": verdict["reason"],
            "templates": out["plan"]["templates"], "rounds": out["round"], "stop": out["stop_reason"],
            "trials": led["trials"], "looks": led["looks"], "required_oos_sharpe": verdict["required_oos_sharpe"],
            "best_oos_sharpe": max((f["oos_sharpe"] for f in led["families"]), default=None),
            "holdout_sharpe": (out.get("holdout") or {}).get("sharpe"),
            "refused_by_code": len(led["dropped"]), "model_calls": len(out["spend"]["calls"]),
            "agent_failures": verdict.get("agent_failures", 0),
            "usd": out["spend"]["usd"], "seconds": round(time.perf_counter() - t0, 1)}


def summarise(cases: list[dict], arm: str) -> dict:
    edge = [c for c in cases if c["truth"] == "edge"]
    noise = [c for c in cases if c["truth"] == "no_edge"]
    out = {
        "edges_recovered": f"{sum(c[arm]['promote'] for c in edge)}/{len(edge)}",
        "noise_promoted": f"{sum(c[arm]['promote'] for c in noise)}/{len(noise)}",
        "trials": sum(c[arm]["trials"] for c in cases),
    }
    if arm.startswith("agents"):
        out |= {"usd": round(sum(c[arm].get("usd", 0) for c in cases), 4),
                "median_seconds_per_study": sorted(c[arm]["seconds"] for c in cases)[len(cases) // 2],
                "errors": sum("error" in c[arm] for c in cases),
                "agent_failures_fell_back": sum(c[arm].get("agent_failures", 0) for c in cases)}
    return out


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--agents", choices=["offline", "llm"])
    ap.add_argument("--models", choices=["mixed", "gemma", "deepseek"], default="mixed",
                    help="model per role for the llm arm (research_bench.agents.MODEL_SETS)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--calibration", action="store_true",
                    help="seeds 1000-1019 (for checking a change; written to .cache, never to results)")
    ap.add_argument("--tag", default="", help="suffix for the results file, e.g. v2")
    a = ap.parse_args(argv)
    cases_in = [(k, s + 999) for k, s in CASES] if a.calibration else CASES
    arms = ["naive", "protocol"] + ([f"agents_{a.agents}"] if a.agents else [])
    cases = []
    for kind, seed in cases_in:
        c = run_case(kind, seed)
        cases.append(c)
        print(f"  seed {seed:>2} {kind:<8} naive {'PROMOTE' if c['naive']['promote'] else 'reject ':<7}"
              f"  protocol {'PROMOTE' if c['protocol']['promote'] else 'reject ':<7} ({c['protocol']['reason']})")
    if a.agents:
        with ThreadPoolExecutor(a.workers) as pool:
            res = list(pool.map(lambda ks: agents_case(*ks, a.agents, a.models), cases_in))
        for c, r in zip(cases, res, strict=True):
            c[f"agents_{a.agents}"] = r
            print(f"  seed {c['seed']:>2} {c['market']:<8} agents {'PROMOTE' if r['promote'] else 'reject ':<7}"
                  f" trials {r['trials']:>4} ${r.get('usd', 0):.4f} {r['seconds']}s "
                  f"({r.get('reason') or r.get('error')})")
    out = {
        "what": "Planted-edge benchmark: 10 markets with a real edge, 10 of pure noise; seeds 1-20 "
                "(calibration used 1000-1019).",
        "date": dt.date.today().isoformat(),
        "protocol": PROTO.__dict__,
        "summary": {arm: summarise(cases, arm) for arm in arms},
        "cases": cases,
    }
    if a.agents:
        out["disclosure"] = DISCLOSURE
        if a.agents == "llm":
            from research_bench.agents import MODEL_SETS
            out["models"] = {r: m for r, (_, m) in MODEL_SETS[a.models].items()}
    suffix = ((f"_agents-{a.agents}" if a.agents else "")
              + (f"-{a.models}" if a.agents == "llm" and a.models != "mixed" else "")
              + (f"_{a.tag}" if a.tag else ""))
    if a.calibration:
        out["what"] = "CALIBRATION run, seeds 1000-1019: for checking changes; not a benchmark result."
        Path(".cache").mkdir(exist_ok=True)
    path = (Path(".cache") / f"calibration_{out['date']}{suffix}.json" if a.calibration
            else Path("results") / f"planted_benchmark_{out['date']}{suffix}.json")
    path.write_text(json.dumps(out, indent=1), encoding="utf-8")
    for arm, s in out["summary"].items():
        print(f"{arm:<15} " + ", ".join(f"{k} {val}" for k, val in s.items()))
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Export research-bench runs (public data only) and the planted benchmark for the website.

    python scripts/export_bench_replays.py .cache/replay_nifty_dips.log .cache/replay_nifty_trend.log ...

Each log is the stdout of one ``python -m research_bench.run`` study; its last line names the
thread and the wall time. The run's full state is read from ``.cache/runs/<thread>.json``.
Writes ``frontend/public/data/bench.json``. Refuses any source that is not public
(NIFTY50+VIX or synthetic:*), so a private-engine run can never reach the site.
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "frontend" / "public" / "data" / "bench.json"
PUBLIC = re.compile(r"^(NIFTY50\+VIX|synthetic:(trend|meanrev|noise):\d+)$")
FAMILY_KEYS = ("id", "template", "trials", "in_sample_sharpe", "oos_sharpe", "positive_folds",
               "passed_walk_forward", "buy_hold_oos_sharpe", "best_params")
LABEL = {"NIFTY50+VIX": "NIFTY 50 + India VIX, daily (public data)"}


def study(log: Path) -> dict:
    m = re.search(r"^thread (\w+) \| (\d+)s", log.read_text(encoding="utf-8"), re.MULTILINE)
    if not m:
        raise SystemExit(f"{log}: no 'thread <id> | <n>s' line")
    s = json.loads((ROOT / ".cache" / "runs" / f"{m[1]}.json").read_text(encoding="utf-8"))
    if not PUBLIC.match(s["source"]):
        raise SystemExit(f"{log}: source {s['source']!r} is not public; refusing to export")
    fams = s["ledger"]["families"]
    refused = defaultdict(list)
    for d in s["ledger"]["dropped"]:
        r, _, text = d.partition(": ")
        refused[int(r.split()[-1])].append(text)
    reviews = {r["round"]: r for r in s["reviews"]}
    rounds = []
    for p in s["proposals"]:
        n = p["round"]
        rounds.append({
            "round": n, "by": "code (baseline)" if p["hypothesis"] == "baseline" and n == 1 else "researcher",
            "diagnosis": p["diagnosis"], "hypothesis": p["hypothesis"],
            "experiments": [{"template": e["template"], "params": e["params"], "rationale": e["rationale"]}
                            for e in p["experiments"]],
            "families": [{k: f[k] for k in FAMILY_KEYS} for f in fams if f["round"] == n],
            "refused_by_code": refused.get(n, []),
            "critic": ({"verdict": reviews[n]["verdict"], "concerns": reviews[n]["concerns"]}
                       if n in reviews else None),
        })
    by_role: dict[str, dict] = {}
    for c in s["spend"]["calls"]:
        r = by_role.setdefault(c["role"], {"calls": 0, "usd": 0.0, "model": c["model"]})
        r["calls"] += 1
        r["usd"] = round(r["usd"] + c["usd"], 6)
    card = s["card"]
    return {
        "id": m[1], "idea": s["idea"], "source": s["source"], "source_label": LABEL.get(s["source"], s["source"]),
        "dataset": {"rows": card["rows"], "start": card["first"], "end": card["last"],
                    "sha256": card["sha256"], "passed": card["passed"]},
        "spec": {"style": s["spec"]["style"], "summary": s["spec"]["summary"]},
        "plan": {k: s["plan"][k] for k in ("hypothesis", "templates", "trial_budget", "rounds", "rationale")},
        "plan_review": s.get("plan_review"), "plan_revisions": s.get("plan_revisions", 0),
        "rounds": rounds, "stop_reason": s["stop_reason"], "verdict": s["verdict"],
        "holdout": s.get("holdout"), "trials": s["ledger"]["trials"], "looks": s["ledger"]["looks"],
        "report": s.get("report"), "report_check": s.get("report_check"),
        "spend": {"usd": s["spend"]["usd"], "calls": len(s["spend"]["calls"]), "by_role": by_role},
        "seconds": int(m[2]), "human": s.get("human"),
    }


def benchmark() -> dict:
    res = ROOT / "results"
    base = json.loads((res / "planted_benchmark_2026-11-16.json").read_text(encoding="utf-8"))["summary"]
    arms = [("Grid search, promote best in-sample", "naive", base["naive"], None),
            ("Grid search + walk-forward + sealed holdout", "protocol", base["protocol"], None)]
    for label, f, key in [("Agents, rules only", "planted_benchmark_2026-11-16_agents-offline.json", "agents_offline"),
                          ("LLM agents v1", "planted_benchmark_2026-11-16_agents-llm.json", "agents_llm"),
                          ("LLM agents v2", "planted_benchmark_2026-11-16_agents-llm_v2.json", "agents_llm")]:
        d = json.loads((res / f).read_text(encoding="utf-8"))
        arms.append((label, key, d["summary"][key], f))
    return {"markets": "20 synthetic markets: 10 with a planted edge, 10 pure noise (seeds 1-20)",
            "arms": [{"label": lab, "edges": s["edges_recovered"], "noise": s["noise_promoted"],
                      "trials": s["trials"], "usd": s.get("usd", 0.0),
                      "median_seconds": s.get("median_seconds_per_study"), "file": f}
                     for lab, _k, s, f in arms]}


def main(argv: list[str]) -> int:
    out = {"studies": [study(Path(a)) for a in argv], "benchmark": benchmark()}
    OUT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(out['studies'])} studies")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

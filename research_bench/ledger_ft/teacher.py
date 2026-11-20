"""The teacher: DeepSeek V3.2 researcher studies on calibration seeds, every call capped and logged.

    AWS_PROFILE=agentic python -m research_bench.ledger_ft.teacher --stage pilot --seeds 1000:1016
    AWS_PROFILE=agentic python -m research_bench.ledger_ft.teacher --stage collect --seeds 1016:1300 --cap 3.5
    python -m research_bench.ledger_ft.teacher --gate          # pilot numbers + the gate decision ($0)

Traces append to ``.cache/ledger_ft/traces/<stage>.jsonl`` (one study per line); a seed already in
any trace file is skipped, so a run can resume and no study is sampled twice. Before each study
the cap must leave room for one study's worst case, else the run stops cleanly.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from research_bench.ledger_ft import label
from research_bench.ledger_ft.seeds import calibration_cases, require_calibration
from research_bench.ledger_ft.spend import SpendLedger

ROOT = Path(".cache") / "ledger_ft"
TRACES = ROOT / "traces"
MIN_ROOM_PER_STUDY = 0.06        # do not start a study unless this much cap is left (worst case seen)

# The gate, fixed before the pilot ran (19 Nov 2026). The pilot failed it ($6.07 projected > $5.00;
# win rate 0.19 < 0.20). Hemant then raised the total cap to $7.00, then to $8.00, and chose to proceed, overriding
# the win-rate test. Both facts are disclosed with the results.
GATE = {"target_wins": 150,          # a usable training set: code-verified wins
        "min_win_rate": 0.20,        # wins per model-written proposal
        "max_total_usd": 8.00,       # pilot + collection + both final evals (was 5.00 when the pilot ran)
        "eval_studies": 20, "eval_arms": 2}


def load_traces(stages: list[str] | None = None) -> list[dict]:
    out = []
    for p in sorted(TRACES.glob("*.jsonl")):
        if stages and p.stem not in stages:
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                t = json.loads(line)
                require_calibration(int(t["seed"]))
                out.append(t)
    return out


def clean_wins(traces: list[dict]) -> int:
    return sum(r["label"] == "win" for t in traces if not t.get("agent_failures") and "error" not in t
               and not t.get("cut_by_cap") for r in label.label_trace(t))


def collect(stage: str, start: int, stop: int, workers: int, cap: float | None,
            target_wins: int | None = None) -> int:
    from research_bench.ledger_ft.harness import mixed_agents, run_study, summarise
    ledger = SpendLedger()
    if cap is not None:
        room = ledger.total_cap - ledger.spent()
        if cap > room + 1e-9:
            print(f"cap ${cap:.2f} > total room ${room:.2f}; refused")
            return 2
        ledger.set_stage_cap(stage, ledger.spent(stage) + cap)
    if stage not in ledger.stage_caps:
        print(f"stage {stage!r} needs --cap")
        return 2
    prior = load_traces()
    done = {t["seed"] for t in prior}
    wins = [clean_wins(prior)]
    todo = [(k, s) for k, s in calibration_cases(start, stop) if s not in done]
    TRACES.mkdir(parents=True, exist_ok=True)
    path, lock, results = TRACES / f"{stage}.jsonl", threading.Lock(), []
    stopped = threading.Event()

    def one(ks: tuple[str, int]) -> None:
        kind, seed = ks
        if stopped.is_set():
            return
        if target_wins is not None and wins[0] >= target_wins:
            stopped.set()
            print(f"  target reached: {wins[0]} clean wins; stopping before seed {seed}")
            return
        if ledger.remaining(stage) < MIN_ROOM_PER_STUDY:
            stopped.set()
            print(f"  cap reached: ${ledger.spent(stage):.4f} spent in {stage}; stopping before seed {seed}")
            return
        t = run_study(kind, seed, mixed_agents(ledger, stage, f"{stage}:{seed}"))
        t["harness"], t["stage"] = "mixed", stage
        if any("BudgetExceeded" in f["failure"] for f in t["failures"]):
            t["cut_by_cap"] = True
        with lock:
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(t) + "\n")
            results.append(t)
            w = clean_wins([t])
            wins[0] += w
            print(f"  seed {seed} {kind:<8} {'PROMOTE' if t['promote'] else 'reject '} trials {t['trials']:>4} "
                  f"proposals {len(t['proposals'])} wins {w} (total {wins[0]}) fails {t['agent_failures']} "
                  f"${t.get('usd', 0):.4f} | {stage} spent ${ledger.spent(stage):.4f}", flush=True)

    with ThreadPoolExecutor(workers) as pool:
        list(pool.map(one, todo))
    if results:
        print(json.dumps(summarise(results)))
    print(f"spend: {stage} ${ledger.spent(stage):.4f}, total ${ledger.spent():.4f} (log {ledger.path})")
    return 0


def gate_report(stage: str = "pilot") -> dict:
    """Wins per dollar on the pilot, the projected cost of a usable set, and the decision."""
    ledger = SpendLedger()
    traces = [t for t in load_traces([stage])]
    clean = [t for t in traces if not t.get("agent_failures") and "error" not in t]
    rows = [r for t in clean for r in label.label_trace(t)]
    wins = [r for r in rows if r["label"] == "win"]
    calls = [json.loads(x) for x in ledger.path.read_text(encoding="utf-8").splitlines() if x.strip()]
    pcalls = [c for c in calls if c["stage"] == stage]
    by_role: dict[str, float] = {}
    for c in pcalls:
        by_role[c["role"]] = by_role.get(c["role"], 0.0) + c["usd"]
    spent = ledger.spent(stage)
    n = max(1, len(traces))
    non_researcher_per_study = sum(u for r, u in by_role.items() if r != "researcher") / n
    win_rate = len(wins) / max(1, len(rows))
    wins_per_usd = len(wins) / spent if spent else 0.0
    need = max(0, GATE["target_wins"] - len(wins))
    collect_usd = need / wins_per_usd if wins_per_usd else float("inf")
    eval_usd = non_researcher_per_study * GATE["eval_studies"] * GATE["eval_arms"]
    projected = ledger.spent() + collect_usd + eval_usd
    reasons = []
    if projected > GATE["max_total_usd"]:
        reasons.append(f"projected total ${projected:.2f} > ${GATE['max_total_usd']:.2f}")
    if win_rate < GATE["min_win_rate"]:
        reasons.append(f"win rate {win_rate:.2f} < {GATE['min_win_rate']}")
    kinds: dict[str, list[int]] = {}
    for r in rows:
        kinds.setdefault(r["kind"], [0, 0])
        kinds[r["kind"]][0] += r["label"] == "win"
        kinds[r["kind"]][1] += 1
    reason_counts: dict[str, int] = {}
    for r in rows:
        reason_counts[r["reason"]] = reason_counts.get(r["reason"], 0) + 1
    return {"stage": stage, "studies": len(traces), "clean_studies": len(clean),
            "proposals": len(rows), "wins": len(wins), "win_rate": round(win_rate, 3),
            "wins_by_kind": {k: f"{w}/{t}" for k, (w, t) in kinds.items()},
            "label_reasons": reason_counts,
            "spent_usd": round(spent, 4), "usd_per_study": round(spent / n, 5),
            "usd_by_role": {k: round(v, 5) for k, v in by_role.items()},
            "wins_per_usd": round(wins_per_usd, 1),
            "projection": {"target_wins": GATE["target_wins"], "more_wins_needed": need,
                           "collect_usd": round(collect_usd, 2), "eval_usd": round(eval_usd, 2),
                           "projected_total_usd": round(projected, 2)},
            "verdicts": {"edges": f"{sum(t['promote'] for t in traces if t['truth'] == 'edge')}/"
                                  f"{sum(t['truth'] == 'edge' for t in traces)}",
                         "noise_promoted": f"{sum(t['promote'] for t in traces if t['truth'] == 'no_edge')}/"
                                           f"{sum(t['truth'] == 'no_edge' for t in traces)}",
                         "trials": sum(t["trials"] for t in traces)},
            "gate": {"passed": not reasons, "reasons": reasons, "thresholds": GATE}}


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="pilot")
    ap.add_argument("--seeds", default="1000:1016", help="start:stop, calibration seeds only")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--cap", type=float, help="USD cap for this stage (pilot is fixed at $0.50)")
    ap.add_argument("--gate", action="store_true", help="print the pilot gate report and exit")
    ap.add_argument("--target-wins", type=int, default=None,
                    help="stop starting studies once all traces hold this many clean wins")
    a = ap.parse_args(argv)
    if a.gate:
        rep = gate_report(a.stage)
        (ROOT / f"gate_{a.stage}.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
        print(json.dumps(rep, indent=1))
        return 0
    start, stop = (int(x) for x in a.seeds.split(":"))
    if a.stage == "pilot" and a.cap is not None:
        print("the pilot cap is fixed at $0.50")
        return 2
    return collect(a.stage, start, stop, a.workers, a.cap, a.target_wins)


if __name__ == "__main__":
    sys.exit(main())

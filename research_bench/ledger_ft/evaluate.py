"""Evaluate a local researcher model (untuned base, or base + ledger-trained adapter).

    # $0: calibration seeds, every other role the rule policy (Stage 0 baseline, student smoke check)
    python -m research_bench.ledger_ft.evaluate --calibration 1900:1912 --model Qwen/Qwen2.5-3B-Instruct
    python -m research_bench.ledger_ft.evaluate --calibration 1900:1912 --adapter .cache/ledger_ft/adapters/a1

    # ONCE: benchmark seeds 1-20, the v2 harness (Gemma intake, DeepSeek planner/critic, capped)
    AWS_PROFILE=agentic python -m research_bench.ledger_ft.evaluate --final --tag student --adapter ... --cap 0.4
    -> results/ledger_ft_<date>_<tag>.json

``--final`` is the only code path in this package that touches seeds 1-20. It writes a marker
before the first study and refuses to start if the marker exists, so each arm is evaluated once
(a crashed run still counts). With an adapter it re-verifies the training set first: the hash
recorded at training time must match the file, and every training seed must be >= 1000.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from research_bench.ledger_ft.seeds import benchmark_cases, calibration_cases

ROOT = Path(".cache") / "ledger_ft"


def check_adapter(adapter: str, calib_seeds: list[int] | None = None) -> dict:
    """The adapter's training set: hash re-verified, seeds re-checked, no overlap with eval seeds."""
    from research_bench.ledger_ft import dataset
    meta = json.loads((Path(adapter) / "training_meta.json").read_text(encoding="utf-8"))
    manifest = json.loads(Path(meta["manifest"]).read_text(encoding="utf-8"))
    if manifest["sha256"] != meta["dataset_sha256"]:
        raise ValueError("adapter was trained on a different dataset than the manifest describes")
    recs = dataset.verify(meta["dataset"], manifest)
    trained = {r["seed"] for r in recs}
    if calib_seeds and trained & set(calib_seeds):
        raise ValueError(f"eval seeds overlap the training seeds: {sorted(trained & set(calib_seeds))[:5]}")
    return {"dataset_sha256": manifest["sha256"], "records": len(recs), "base": meta["base"],
            "steps": meta.get("steps"), "train_seeds": [min(trained), max(trained)]}


def strip(t: dict) -> dict:
    """A trace without the (long) prompts, for the results file."""
    return {**t, "proposals": [{k: v for k, v in p.items() if k != "user"} for p in t["proposals"]]}


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=None, help="HF base model (default: the adapter's base)")
    ap.add_argument("--adapter", default=None)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--calibration", help="start:stop calibration seeds, offline roles, $0")
    g.add_argument("--final", action="store_true", help="benchmark seeds 1-20, ONCE per tag")
    ap.add_argument("--tag", default=None)
    ap.add_argument("--cap", type=float, default=None, help="USD cap for the final eval's paid roles")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args(argv)

    from llm_gateway.hf_local_provider import HFLocalProvider
    from research_bench.ledger_ft.harness import ResearcherOnly, mixed_agents, run_study, summarise

    if a.calibration:
        start, stop = (int(x) for x in a.calibration.split(":"))
        cases = calibration_cases(start, stop)
    else:
        cases = benchmark_cases()
    adapter_info = check_adapter(a.adapter, [s for _, s in cases] if a.calibration else None) if a.adapter else None
    base = a.model or (adapter_info or {}).get("base") or "Qwen/Qwen2.5-3B-Instruct"
    tag = a.tag or ("student" if a.adapter else "base")
    researcher = HFLocalProvider(base, adapter=a.adapter)

    ledger = None
    if a.final:
        from research_bench.ledger_ft.spend import SpendLedger
        marker = ROOT / f"final_eval_{tag}.started"
        if marker.exists():
            print(f"refused: the final eval for {tag!r} already ran ({marker}); seeds 1-20 are evaluated once")
            return 2
        if a.cap is None:
            print("--final needs --cap")
            return 2
        ledger = SpendLedger()
        if a.cap > ledger.total_cap - ledger.spent() + 1e-9:
            print(f"cap ${a.cap:.2f} > total room ${ledger.total_cap - ledger.spent():.2f}; refused")
            return 2
        ledger.set_stage_cap(f"eval_{tag}", ledger.spent(f"eval_{tag}") + a.cap)
        ROOT.mkdir(parents=True, exist_ok=True)
        marker.write_text(dt.datetime.now().isoformat(), encoding="utf-8")

    def agents_for(seed: int):
        if a.final:
            return mixed_agents(ledger, f"eval_{tag}", f"eval_{tag}:{seed}", researcher=researcher)
        return ResearcherOnly(researcher)

    def one(ks: tuple[str, int]) -> dict:
        t = run_study(ks[0], ks[1], agents_for(ks[1]))
        print(f"  seed {t['seed']:>4} {t['kind']:<8} {'PROMOTE' if t['promote'] else 'reject '} "
              f"trials {t['trials']:>4} ok-calls {len(t['proposals'])} fallbacks {t['agent_failures']} "
              f"${t.get('usd', 0):.4f} {t['seconds']}s ({t.get('reason') or t.get('error')})", flush=True)
        return t

    researcher.complete  # noqa: B018 - fail early if the class is broken
    from llm_gateway.hf_local_provider import load
    load(researcher.base, researcher.adapter)       # load once before the threads start
    with ThreadPoolExecutor(a.workers) as pool:
        traces = list(pool.map(one, cases))
    out = {"what": ("FINAL eval on benchmark seeds 1-20" if a.final else
                    f"calibration check, seeds {a.calibration}, other roles = rule policy ($0)"),
           "date": dt.date.today().isoformat(), "tag": tag,
           "harness": "mixed (v2: Gemma intake, DeepSeek planner/plan critic/critic; researcher local)"
                      if a.final else "offline-roles",
           "researcher": researcher.model, "adapter": adapter_info,
           "summary": summarise(traces), "cases": [strip(t) for t in traces]}
    if a.final:
        out["spend_ledger_usd"] = ledger.spent(f"eval_{tag}")
        path = Path("results") / f"ledger_ft_{out['date']}_{tag}.json"
    else:
        (ROOT / "eval").mkdir(parents=True, exist_ok=True)
        path = ROOT / "eval" / f"calib_{a.calibration.replace(':', '-')}_{tag}.json"
    path.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out["summary"]))
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

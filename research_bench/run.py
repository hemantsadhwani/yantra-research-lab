"""Run a study.

    AWS_PROFILE=agentic python -m research_bench.run --idea "Buy oversold dips in an uptrend"
    python -m research_bench.run --idea "..." --offline                 # no model, no key
    python -m research_bench.run --resume <thread> --answer "continuation"   (or --decision approve)

Data: ``--source NIFTY50+VIX`` (default, public daily data) or ``synthetic:<kind>:<seed>``.
Engine: in-process by default; ``--engine mcp`` uses the public MCP server; ``--engine-cmd
"<command>"`` launches any server with the same tools (e.g. a private one over real backtests),
and ``--source`` then names one of its datasets.
The run is checkpointed in ``.cache/bench.sqlite``; it stops for questions and before promotion.
The full state (ledger, spend, report) is written to ``.cache/runs/<thread>.json``.
"""

from __future__ import annotations

import argparse
import json
import shlex
import sqlite3
import sys
import time
import uuid
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from research_bench.agents import LLMAgents, OfflineAgents
from research_bench.graph import build, new_state

RUNS = Path(".cache") / "runs"


def summary(out: dict) -> str:
    lines = []
    for p in out.get("proposals", []):
        lines.append(f"round {p['round']}: {p['hypothesis'][:110]}")
        for e in p["experiments"]:
            lines.append(f"    try {e['template']} {e['params']}  ({e['rationale'][:80]})")
    for f in out.get("ledger", {}).get("families", []):
        lines.append(f"  {f['id']} {f['template']:<20} trials {f['trials']:>4}  IS {f['in_sample_sharpe']:>6}  "
                     f"OOS {f['oos_sharpe']:>6}  +folds {f['positive_folds']}  B&H OOS {f['buy_hold_oos_sharpe']}")
    for r in out.get("reviews", []):
        lines.append(f"critic r{r['round']}: {r['verdict']} {r['concerns'][:2]}")
    if out.get("verdict"):
        lines.append(f"stop: {out.get('stop_reason')} | verdict: {out['verdict']['decision']} - {out['verdict']['reason']}")
    sp = out.get("spend", {})
    lines.append(f"trials {out.get('ledger', {}).get('trials')} | looks {out.get('ledger', {}).get('looks')} | "
                 f"model calls {len(sp.get('calls', []))} | ${sp.get('usd', 0):.4f}")
    if out.get("report"):
        r = out["report"]
        lines += ["", r["title"], r["summary"], *[f"- {x}" for x in r["findings"]], r["verdict"],
                  f"(numbers checked: {'all from the ledger' if out['report_check']['passed'] else out['report_check']})"]
    if out.get("__interrupt__"):
        lines.append(f"PAUSED: {out['__interrupt__'][0].value}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--idea")
    ap.add_argument("--source", default="NIFTY50+VIX")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--budget-usd", type=float, default=0.05)
    ap.add_argument("--resume")
    ap.add_argument("--answer")
    ap.add_argument("--decision", choices=["approve", "reject"])
    ap.add_argument("--engine", choices=["local", "mcp"], default="local")
    ap.add_argument("--engine-cmd", help="command that starts a private MCP engine server")
    ap.add_argument("--engine-cwd")
    a = ap.parse_args(argv)
    Path(".cache").mkdir(exist_ok=True)
    RUNS.mkdir(parents=True, exist_ok=True)
    saver = SqliteSaver(sqlite3.connect(".cache/bench.sqlite", check_same_thread=False))
    engine = None
    if a.engine_cmd or a.engine == "mcp":
        from research_bench.engine import MCPEngine
        engine = MCPEngine(argv=shlex.split(a.engine_cmd, posix=False) if a.engine_cmd else None, cwd=a.engine_cwd)
    thread = a.resume or uuid.uuid4().hex[:8]
    g = build(OfflineAgents() if a.offline else LLMAgents(), checkpointer=saver, engine=engine, study=thread)
    cfg = {"configurable": {"thread_id": thread}, "recursion_limit": 80}
    t0 = time.time()
    if a.resume:
        out = g.invoke(Command(resume=a.answer or a.decision), cfg)
    else:
        if not a.idea:
            ap.error("--idea is required for a new study")
        out = g.invoke(new_state(a.idea, a.source, budget_usd=a.budget_usd), cfg)
    print(summary(out))
    print(f"\nthread {thread} | {time.time() - t0:.0f}s")
    (RUNS / f"{thread}.json").write_text(json.dumps({k: v for k, v in out.items() if k != "__interrupt__"},
                                                    indent=1, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())

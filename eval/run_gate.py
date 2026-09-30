"""CI eval-gate: the agent loop must still discover a variant that beats the baseline.

Two arms, one discipline — never ship a change that makes the research loop worse:

    stdlib  research_lab.supervisor.Supervisor (zero deps, the clone-and-run path)
    graph   python -m research_lab.run_graph --no-gate --assert-beats-baseline
            (the LangGraph loop; needs the ``agents`` extra)

    python -m eval.run_gate                # --arm both (default)
    python -m eval.run_gate --arm stdlib   # core CI job, no extras installed
    python -m eval.run_gate --arm graph    # agents CI job; FAILS if langgraph is missing

With ``--arm both`` and langgraph not installed, the graph arm is SKIPPED with a message
(the stdlib story stays runnable); an explicit ``--arm graph`` FAILS instead, so the CI
job that is supposed to prove the graph loop cannot pass by accident. Both arms run
offline and deterministic (seed 3, hashed embedder, no API key). Exit 1 on any failure.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

# Windows consoles default to cp1252 and mangle the arrow in the verdict line.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

SEED, ITERATIONS, VARIANTS = 3, 5, 6
_ROOT = Path(__file__).resolve().parent.parent


def stdlib_arm() -> bool:
    from research_lab.agents.evaluator import score_result
    from research_lab.supervisor import Supervisor

    run = Supervisor(seed=SEED).run(iterations=ITERATIONS, variants_per_iter=VARIANTS)
    best = run.best
    baseline_score = score_result(run.baseline)
    if best is None or best.evaluation.score <= baseline_score or best.evaluation.verdict != "promote?":
        got = f"{best.evaluation.score:.1f}" if best else "none"
        print(f"EVAL-GATE FAIL (stdlib) · best={got} baseline={baseline_score:.1f}")
        return False
    print(f"EVAL-GATE PASS (stdlib) · best {best.variant.id} score {best.evaluation.score:.1f} "
          f"> baseline {baseline_score:.1f} ({best.evaluation.verdict})")
    return True


def _graph_scores(db: str, thread: str) -> tuple[str, float, float] | None:
    """Read (best id, best score, baseline score) back from the run's checkpoint."""
    try:
        from research_lab.graph import best_ranked, build_graph, default_checkpointer

        state = build_graph(default_checkpointer(db)).get_state(
            {"configurable": {"thread_id": thread}}).values
        best = best_ranked(state.get("ranked", []))
        if best is None:
            return None
        return best["variant"]["id"], best["evaluation"]["score"], state["baseline_score"]
    except Exception as exc:  # noqa: BLE001 - reporting only; the exit code is the gate
        print(f"  (could not read scores from checkpoint: {exc!r})", file=sys.stderr)
        return None


def graph_arm() -> bool:
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    thread = f"gate-{ts}"
    env = {**os.environ, "YANTRA_EMBEDDER": "hashed", "ANTHROPIC_API_KEY": ""}
    with tempfile.TemporaryDirectory(prefix="yantra-gate-") as tmp:
        db = str(Path(tmp) / "checkpoints.sqlite")
        cmd = [sys.executable, "-m", "research_lab.run_graph",
               "--iterations", str(ITERATIONS), "--variants", str(VARIANTS),
               "--seed", str(SEED), "--no-gate", "--assert-beats-baseline",
               "--db", db, "--thread", thread]
        proc = subprocess.run(cmd, cwd=_ROOT, env=env, capture_output=True, text=True,
                              check=False)
        if proc.returncode != 0:
            sys.stdout.write(proc.stdout)
            sys.stderr.write(proc.stderr)
            print(f"EVAL-GATE FAIL (graph) · run_graph exited {proc.returncode} "
                  f"(thread {thread})")
            return False
        scores = _graph_scores(db, thread)
    if scores is None:
        print(f"EVAL-GATE FAIL (graph) · run_graph passed but no ranked variant found "
              f"(thread {thread})")
        return False
    best_id, best, baseline = scores
    print(f"EVAL-GATE PASS (graph) · best {best_id} score {best:.1f} > baseline "
          f"{baseline:.1f} (thread {thread})")
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Loop-beats-baseline eval gate.")
    ap.add_argument("--arm", choices=["stdlib", "graph", "both"], default="both")
    args = ap.parse_args(argv)

    ok = True
    if args.arm in ("stdlib", "both"):
        ok &= stdlib_arm()
    if args.arm in ("graph", "both"):
        if importlib.util.find_spec("langgraph") is None:
            if args.arm == "graph":
                print("EVAL-GATE FAIL (graph) · langgraph is not installed "
                      "(pip install -e '.[agents]')")
                ok = False
            else:
                print("EVAL-GATE SKIP (graph) · langgraph not installed; "
                      "install the agents extra to gate the graph loop too")
        else:
            ok &= graph_arm()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

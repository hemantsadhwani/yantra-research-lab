"""Judge eval: does the LLM judge agree with 12 hand-labelled golden cases?

    python -m eval.judge_eval                 # real provider ($LLM_PROVIDER; needs a key, costs < 1 cent)
    python -m eval.judge_eval --fake          # offline: scripted FakeProvider echoing the labels

Golden set: ``eval/datasets/judge_golden.jsonl``. Params and metrics are real engine output
(``synthetic_engine.run_backtest``) against the ``synthetic-meanrev`` baseline; the rationales
and labels are hand-written: 4 consistent / low risk, 3 rationales contradicted by the metrics,
3 boundary-hugging parameters (within 2% of a PARAM_SPACE bound), 2 thin trade counts.

A case **agrees** when ``rationale_consistent`` matches and the judge's ``overfit_risk`` is on
the same side of the veto line (``high`` vs not ``high``) as the label — those are the only two
distinctions ``Judge.apply`` acts on. Exact three-way ``overfit_risk`` agreement is printed too,
for information. Exits 1 if fewer than 9/12 cases agree (or the judge abstained on any case).

``--fake`` exercises the loader, the prompt path through ``Judge.judge`` and the scorer with no
network; it proves the harness, not the model. Not run in CI: the real mode needs a key.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

GOLDEN = Path(__file__).resolve().parent / "datasets" / "judge_golden.jsonl"
PASS_AT = 9
RISKS = ("low", "medium", "high")


def load_golden(path: Path = GOLDEN) -> list[dict[str, Any]]:
    """Load and shape-check every row (raises ``ValueError`` naming the bad row)."""
    rows: list[dict[str, Any]] = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        try:
            assert isinstance(row["id"], str)
            v = row["variant"]
            assert isinstance(v["id"], str) and isinstance(v["rationale"], str)
            assert set(v["params"]) == {"lookback", "z_entry", "z_exit", "stop_pct"}
            for key in ("result", "baseline"):
                m = row[key]
                assert set(m) == {"return_pct", "win_rate", "max_drawdown_pct", "trades"}
                assert 0.0 <= m["win_rate"] <= 1.0 and isinstance(m["trades"], int)
            exp = row["expected"]
            assert isinstance(exp["rationale_consistent"], bool)
            assert exp["overfit_risk"] in RISKS
        except (AssertionError, KeyError, TypeError) as e:
            raise ValueError(f"{path.name}:{n}: malformed golden row ({e!r})") from e
        rows.append(row)
    return rows


def _to_objects(row: dict[str, Any]):
    from research_lab.schemas import BacktestResult, StrategyVariant

    def result(vid: str, m: dict[str, Any]) -> BacktestResult:
        return BacktestResult(variant_id=vid, total_return_pct=m["return_pct"],
                              trades=m["trades"], win_rate=m["win_rate"],
                              max_drawdown_pct=m["max_drawdown_pct"], sharpe=0.0)

    v = row["variant"]
    variant = StrategyVariant(id=v["id"], params=dict(v["params"]), rationale=v["rationale"])
    return variant, result(v["id"], row["result"]), result("baseline", row["baseline"])


def fake_provider(rows: list[dict[str, Any]]):
    """A FakeProvider scripted to echo each row's expected verdict (offline harness check)."""
    from llm_gateway import FakeProvider
    from research_lab.schemas_llm import JudgeVerdict

    return FakeProvider([
        JudgeVerdict(rationale_consistent=r["expected"]["rationale_consistent"],
                     overfit_risk=r["expected"]["overfit_risk"], plausibility=3,
                     note="scripted") for r in rows
    ])


def run(rows: list[dict[str, Any]], provider: Any) -> dict[str, Any]:
    from research_lab.agents.judge import Judge

    judge = Judge(provider=provider, top_k=len(rows))
    rc_ok = risk_exact = agree = 0
    lines: list[str] = []
    for row in rows:
        variant, result, baseline = _to_objects(row)
        verdict = judge.judge(variant, result, baseline,
                              "golden case: judged in isolation, no run history.")
        exp = row["expected"]
        if verdict is None:
            lines.append(f"  {row['id']}  ABSTAIN")
            continue
        rc = verdict.rationale_consistent == exp["rationale_consistent"]
        ex = verdict.overfit_risk == exp["overfit_risk"]
        side = (verdict.overfit_risk == "high") == (exp["overfit_risk"] == "high")
        rc_ok += rc
        risk_exact += ex
        agree += rc and side
        mark = "ok  " if rc and side else "MISS"
        lines.append(f"  {row['id']}  {mark} rationale_consistent {verdict.rationale_consistent!s:<5}"
                     f" (exp {exp['rationale_consistent']!s:<5}) · overfit_risk "
                     f"{verdict.overfit_risk:<6} (exp {exp['overfit_risk']:<6}) · {verdict.note}")
    return {"n": len(rows), "rationale": rc_ok, "overfit_exact": risk_exact, "agree": agree,
            "abstained": judge.judge_failures, "lines": lines,
            "cost_usd": judge.judge_cost_usd}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fake", action="store_true",
                    help="offline: FakeProvider echoing the labels (tests the harness)")
    ap.add_argument("--provider", choices=["anthropic", "bedrock", "ollama"], default=None)
    ap.add_argument("--golden", type=Path, default=GOLDEN)
    args = ap.parse_args(argv)

    rows = load_golden(args.golden)
    if args.fake:
        provider = fake_provider(rows)
    else:
        try:
            from load_env import load_env
            load_env()
        except ImportError:
            pass
        from llm_gateway import get_provider
        provider = get_provider(args.provider)
    out = run(rows, provider)
    print(f"judge eval · {getattr(provider, 'name', '?')}/{getattr(provider, 'model', '?')}"
          f" · {out['n']} golden cases")
    print("\n".join(out["lines"]))
    n = out["n"]
    print(f"  rationale_consistent agreement: {out['rationale']}/{n}")
    print(f"  overfit_risk exact agreement:   {out['overfit_exact']}/{n}  (info)")
    print(f"  case agreement (veto-relevant): {out['agree']}/{n}  (pass ≥ {PASS_AT})"
          f" · abstained {out['abstained']} · ${out['cost_usd']:.4f}")
    if out["abstained"] or out["agree"] < PASS_AT:
        print("  FAIL", file=sys.stderr)
        return 1
    print("  PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())

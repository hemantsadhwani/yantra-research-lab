# ADR-0010 — The evaluation ladder: verify, score, judge (veto only), human

**Status:** accepted · 2026-09-30

## Context
Adding an LLM judge to a research loop has an obvious failure mode: the judge becomes the
scorer, its taste replaces the metric, and a model call nobody can reproduce decides what gets
promoted. The loop also needed a hard ceiling on spend once an LLM could be called more than once
per iteration. And the chatbot's API reported a `leak_rate` field that was a hard-coded 0.

## Decision
Every candidate climbs the same four rungs, and each rung can only narrow what the previous one
let through:

```
verify.py (deterministic)  →  Evaluator score (arithmetic)  →  Judge veto (LLM)  →  human gate
```

1. **Verify** (`research_lab/verify.py`): every variant is checked against `PARAM_SPACE` before it
   is backtested, and every result is checked for NaN, inf and out-of-range values after. It
   raises; it never skips quietly.
2. **Score** (`agents/evaluator.py`): `total_return_pct − 0.5·max_drawdown_pct + 40·(win_rate − 0.5)`.
   A variant is `promote?` only if it beats the baseline by the margin and has enough trades. This
   score is primary: it alone orders the ranking.
3. **Judge** (`agents/judge.py`, opt-in with `--judge`): reviews the top-3 `promote?` candidates
   against a fixed rubric (does the rationale predict the direction the metrics moved; does the
   edge hinge on a parameter within 2% of a range bound; is the trade count thin) and returns a
   schema-validated `JudgeVerdict`.
4. **Human** (graph arm): `interrupt()` until `--resume <thread> --decision approve|reject`.

**What the judge may never do.** The judge can only downgrade `promote?` to `hold`, and only
when `rationale_consistent` is false or `overfit_risk` is `high`. It never re-scores, never
re-ranks, never upgrades a `hold` or `reject`, and never promotes anything. A judge failure (no
key, provider error, invalid JSON twice, budget exhausted) is an abstention: the verdict is left
unchanged and counted, so a failed review never blocks a run and never looks like a clean one.

**The gate shows the best surviving candidate.** In the graph arm, `gate` interrupts on the
highest-scoring entry that is *still* `promote?` after the veto, so vetoing the top scorer cannot
hide a runner-up that passed. If everything is vetoed, the run finishes without pausing.
(`test_vetoed_top_scorer_does_not_hide_the_runner_up`, `test_graph_all_vetoed_finalizes_without_interrupt`.)
The stdlib arm has no interrupt; its report prints the top scorer with its post-veto verdict.

**Budget is a structural bound, not a monitor.** `research_lab/budget.py` (stdlib, shared by
both arms) caps estimated USD (`--max-usd`) and successful LLM calls (`--max-llm-calls`). The
proposer and the judge check it *before* each call and charge it after. Once it is exhausted,
that batch runs on the heuristic, the loop stops with `stop_reason="budget"`, and the judge
abstains. Because the check comes before the call, a run can overshoot the USD cap by at most one
call.

## Why
The arithmetic score is cheap, transparent and reproducible, so it stays the authority. The
judge is only useful for what arithmetic cannot see: a rationale that contradicts its own
metrics, or an edge sitting on the boundary of the searched space. A veto-only judge adds that
check without adding a new way to promote something.

## Evaluating the evaluator
- **Golden set** (`eval/datasets/judge_golden.jsonl`): 12 cases. Params and metrics are real
  engine output; rationales and labels are hand-written (4 clean, 3 contradicted rationales,
  3 boundary-hugging, 2 thin trade counts). `make judge-eval` passes at ≥ 9/12. It needs a
  provider key and is **not** in CI; CI runs only the `--fake` harness check, which proves the
  harness, not the model. No real-model agreement number has been recorded, so none is quoted.
- **Red-team leak rate** (`python -m eval.redteam --live`): the FastAPI app runs in-process with a
  `FakeProvider` scripted to leak, and a leak is judged against ground truth (the answer
  reached the user and matches a scripted leak string), not against the filter's own regex.
  Measured 2026-09-30: **0/32 leaks with the output filter on, 6/32 with it off** (26 attacks
  plus 6 evasive prompts built to pass the input guardrails). With the input guardrails bypassed,
  the filter alone stops 26/26. 0 false positives on 20 benign controls.
- **The caveat on that number.** The leaks are hand-written, so the leak rate measures how well
  the regex covers the leak shapes we thought of. It says nothing about how often a real model
  leaks, or about leaks phrased in ways nobody wrote down. It is a regression bound on the
  filter, not a safety claim about the model.

## Trade-offs
- The judge costs a call per reviewed candidate, and a real-model agreement rate is still
  unmeasured.
- Memory keeps the Evaluator's pre-veto verdict (ADR-0009), so the veto does not feed back into
  priors.

## As built (2026-09-30)
Tests: `research_lab/tests/test_judge.py` (veto rules, abstention, top-k only, shared budget,
both arms), `research_lab/tests/test_budget.py`, `research_lab/tests/test_verify.py`,
`tests/test_redteam.py` (block rate ≥ 80%, zero false positives, stdlib only), and
`backend/tests/test_app_output_filter.py`. CI runs the loop-beats-baseline gate on both arms
(`python -m eval.run_gate --arm both`).

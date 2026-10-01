# ADR-0003 — Bounded autonomy: a workflow-shaped loop with agentic steps + HITL

**Status:** accepted · 2026-07-04

**Decision.** The research loop is a **bounded** supervisor–worker workflow: propose → backtest →
judge → rank → remember → iterate, stopped by an **iteration budget** (a USD / LLM-call cap was added
on 2026-09-30, see the addendum; there is no token budget), with a
**human-in-the-loop** gate before any promotion (the top variant is `promote?`, never
auto-promoted). Memory steers proposals (exploit best-so-far + explore).

**Why agentic at all.** The variant search space is open-ended, so the proposer must *reason about
what to try next* — genuine grounds for autonomy. But full autonomy costs latency, money, and
variance, so it is **deliberately bounded**. *"Pay for autonomy only where the problem demands it."*

**Why a workflow shape.** Predictable control flow is cheaper, debuggable, and reliable. The
production build re-expresses this exact loop as a **LangGraph StateGraph** to gain checkpointing,
streaming, and HITL interrupts — the control logic here is the spec.

**Tier-1 vs production swaps (same shapes, mechanical).**
- Proposer heuristic → structured **LLM** proposal (Claude via the model gateway). ✅ *built —
  see the addendum below.*
- Evaluator score → score **+ LLM-as-judge** rubric + regression eval set in CI.
- Episodic memory → **semantic + procedural** memory over SQLite + sqlite-vec.
- Dataclasses → **Pydantic v2** validated I/O.

**Reliability.** Deterministic engine + fixed baseline = the loop's own eval-gate (`eval/run_gate.py`):
if a change stops the loop beating the baseline, CI blocks promotion.
</content>

## Addendum — the proposer swap, built (2026-09-13)

The first swap on that list is no longer hypothetical. `Proposer(use_llm=True)` routes proposals
through a structured Claude call while `propose(n, memory)` stays the only public method, so the
supervisor, the schemas, the verification hooks, the evaluator and the HITL gate are **unchanged
by the swap** — which is what "same shapes, mechanical" was asserting. It is now demonstrable
rather than claimed, and it is the concrete answer to *"isn't building on the Claude SDK vendor
lock-in?"*: the lock-in is at the model layer, not the architecture layer.

Two things the build made explicit that the ADR did not say:

**The deterministic path is not scaffolding — it is kept, and it stays the default.** A loop that
runs reproducibly with no API key is worth more than a tidier codebase, both as an offline
property and because keeping both sides is what makes the comparison below possible.

**A model in the loop does not get to bypass the contract.** LLM proposals are clamped into the
declared parameter space and still pass through `verify_variant`; unusable output falls back to
the heuristic for that batch and is counted rather than hidden. Bounded autonomy applies to the
agent's *output*, not just its iteration budget.

**What it bought, measured** (`research_lab/experiments/context_study.py`, three seeds,
`claude-haiku-4-5`, raw runs in `results/`): compaction held 95% of the full-history score for
46% of the input tokens. The LLM proposer averaged 35.4 against the heuristic's 30.4 — better,
but on one of three seeds the free, instant, deterministic proposer beat two of the three LLM
context constructions. Whether full history genuinely beats compaction is not settled by n=3;
the per-seed spread is wider than the gap. The decision this supports is unchanged: **pay for
autonomy where the problem demands it**, and measure what it costs.

## Addendum — the second and third swaps, and an enforced budget (2026-09-30)

- **Evaluator score → score + LLM-as-judge: built, veto-only.** `research_lab/agents/judge.py`
  (`--judge`) reviews the top-3 `promote?` candidates and can only downgrade them to `hold`. The
  arithmetic score stays primary. See [ADR-0010](0010-evaluation-ladder.md).
- **Episodic memory → semantic + procedural: built, over SQLite, without sqlite-vec.**
  `research_lab/memory_store.py` (`--memory sqlite`); cosine is a Python loop until the trial
  count justifies an extension. See [ADR-0009](0009-persistent-memory.md).
- **Dataclasses → Pydantic v2: done at the LLM boundary only.** `schemas_llm.py` validates model
  replies; `schemas.py` stays stdlib dataclasses so the default path imports nothing.
- **The budget is enforced, not described.** `research_lab/budget.py` caps estimated USD and LLM
  calls on both arms, is checked before every model call, and stops the loop with
  `stop_reason="budget"`. The iteration count still bounds the shape of the run.
- **The LangGraph re-expression exists** ([ADR-0007](0007-langgraph-primary-orchestrator.md)),
  and the human gate is now a real `interrupt()`, not a printed line.

The seam held again. The judge and the persistent store plug into both arms with no change to
the loop's control flow, and with neither enabled the stdlib report is unchanged: `make demo` output
before WP3 (`667ed8e`) and after WP5 matches byte for byte, and `test_stdlib_default_is_unchanged` and `test_inmem_memory_unchanged`
guard the ranking.

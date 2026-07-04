# ADR-0003 — Bounded autonomy: a workflow-shaped loop with agentic steps + HITL

**Status:** accepted · 2026-07-04

**Decision.** The research loop is a **bounded** supervisor–worker workflow: propose → backtest →
judge → rank → remember → iterate, stopped by an **iteration/token budget**, with a
**human-in-the-loop** gate before any promotion (the top variant is `promote?`, never
auto-promoted). Memory steers proposals (exploit best-so-far + explore).

**Why agentic at all.** The variant search space is open-ended, so the proposer must *reason about
what to try next* — genuine grounds for autonomy. But full autonomy costs latency, money, and
variance, so it is **deliberately bounded**. *"Pay for autonomy only where the problem demands it."*

**Why a workflow shape.** Predictable control flow is cheaper, debuggable, and reliable. The
production build re-expresses this exact loop as a **LangGraph StateGraph** to gain checkpointing,
streaming, and HITL interrupts — the control logic here is the spec.

**Tier-1 vs production swaps (same shapes, mechanical).**
- Proposer heuristic → structured **LLM** proposal (Claude via the model gateway).
- Evaluator score → score **+ LLM-as-judge** rubric + regression eval set in CI.
- Episodic memory → **semantic + procedural** memory over SQLite + sqlite-vec.
- Dataclasses → **Pydantic v2** validated I/O.

**Reliability.** Deterministic engine + fixed baseline = the loop's own eval-gate (`eval/run_gate.py`):
if a change stops the loop beating the baseline, CI blocks promotion.
</content>

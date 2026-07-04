# 01 · Strategy research — the agentic core

**Goal.** Replace the manual quant-research loop (hypothesize → backtest → compare → tweak,
one idea at a time) with an autonomous loop that runs in parallel and **compounds via memory**.

## The loop
```
plan → propose N variants → backtest each → judge vs baseline → rank → remember best → iterate
       (memory-guided)       (MCP tool)      (risk-adj + judge)         (until budget)   HITL gate
```
- **Supervisor–worker** topology — one supervisor decomposes and dispatches to specialist workers
  (proposer, backtester, evaluator), then ranks and iterates.
- **Bounded autonomy** — capped by an iteration/token **budget**; nothing promotes autonomously,
  the top variant is surfaced as `promote?` behind a **human-in-the-loop** gate.
- **Offline↔online parity** — every variant is judged on the *same* deterministic market data, so
  no variant gets luckier inputs. Reproducibility is a design property, not an accident.

## Why agentic (and why bounded)
The variant search space is open-ended, so the proposer must *reason about what to try next* from
what worked — genuine grounds for autonomy. But autonomy costs latency, money, and variance, so it
is deliberately bounded. **Pay for autonomy only where the problem demands it.**

## Decisions (ADR lens)
| Decision | Why / trade-off |
|---|---|
| Supervisor–worker vs single agent | controllable, debuggable, a natural place for budgets + guardrails |
| Bounded loop vs open-ended agent | flexibility where needed, but max-iterations/token budget caps cost/variance |
| MCP tool for backtests | host-agnostic contract; swap the engine without touching agents ([ADR-0002](../docs/adr/0002-mcp-wrap-the-engine.md)) |
| LLM-as-judge + a metric score | metric is cheap and transparent; the judge catches overfit/implausible edges |
| Deterministic engine + fixed baseline | doubles as the loop's own **eval-gate** — a change that stops beating baseline fails CI |

## Production mapping
The reference implementation runs the loop in plain Python (workflow-shaped, zero deps). The
production build re-expresses it as a **LangGraph `StateGraph`** for checkpointing, streaming, and
HITL interrupts; the proposer becomes a structured **LLM** call; the evaluator adds an LLM-as-judge
rubric and a regression eval set gated in CI. The control logic is unchanged — see
[ADR-0003](../docs/adr/0003-bounded-autonomy.md).
</content>

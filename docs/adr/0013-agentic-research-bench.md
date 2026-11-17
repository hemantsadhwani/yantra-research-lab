# ADR-0013: The agentic research bench — agents decide, code verifies, a human promotes

Date: 2026-11-16 · Status: accepted (building)

## Context

The original loop (ADR-0003, ADR-0007) is a workflow: code fixes every step and the only model
call fills in parameters. Research by hand takes 1–3 weeks per idea (the owner's measured
baseline), and long optimisation finds patterns in noise. The planted-edge benchmark
(`eval/planted_benchmark.py`) quantifies it: naive grid search promoted 4 of 10 pure-noise
markets; walk-forward + a locked holdout promoted 0 of 10 and recovered 9 of 10 real edges, at
1,260 trials per idea. The business objective: turn an idea into a validated verdict in under an
hour, at cents per study, with false discoveries stopped and every number auditable.

## Decision

A supervisor-led multi-agent system in a new package, `research_bench/`, on the public engine
(`quant_engine/`). The old loop stays until it is retired.

| Agent | Decides | Tools | Model (to be confirmed by the role benchmark) |
|---|---|---|---|
| Intake | which questions to ask (≤3), when the spec is complete | none | Gemma 3 12B |
| Planner | hypothesis, templates, parameter sub-space, trial budget, rounds | template catalogue | DeepSeek V3.2 |
| Data | which allow-listed source, what to do on a failure | `fetch` (allow-list), dataset card | Gemma 3 12B |
| Researcher | what to test next and why, from the results so far | `run_experiments`, `regime_split`, `trade_breakdown`, `neighbourhood` | DeepSeek V3.2 |
| Critic | whether a result is believable; may demand a robustness test or veto | read-only ledger | DeepSeek V3.2 |
| Reporter | the write-up | read-only ledger; every number checked | Gemma 3 12B |
| Supervisor | routing, stop, opening the holdout | code, not a model | — |

**Code owns truth.** The engine computes every metric; the look-ahead test covers every
template; thresholds of the success test are fixed in code (a planner may tighten, never
loosen); the holdout is sealed until the supervisor opens it once for at most two finalists;
every parameter set evaluated is a counted trial in the ledger; the report's numbers are
checked against the ledger. **A human promotes**: the graph interrupts before promotion
(benchmark mode records the verdict instead).

**Context is the ledger, not the chat.** Each agent call gets a short brief built from the
experiment ledger (best results, what was tried, what failed). Long runs do not grow a context
window, which is where models start inventing results.

**Validation looks are counted.** An agent that adapts to walk-forward results turns them into
in-sample data. So walk-forward is the validation set, its looks are counted and shown to the
critic, and the holdout stays sealed; the benchmark measures whether the agents overfit it.

**Stop rules (code):** max rounds (6), trial budget (planner's, capped at 400), no
improvement in validation for 2 rounds, USD cap per run (default $0.05), critic veto.

**Same tools everywhere.** The researcher's tools have the signatures of MCP tools; the MCP
server wraps the public engine, and a private server can wrap a private engine (e.g. the
owner's options backtests) without changing the agents. Only metrics cross the boundary.

## Consequences

- The claim "multi-agent" becomes true and testable: the benchmark gets a third arm, agents +
  protocol, reported with trials, cost and time against the other two.
- Expected gain is in cost and time (far fewer than 1,260 trials per idea) and in recall
  (diagnosis can rescue a real edge the blind grid missed). If the agents do not beat the
  grid + protocol arm on those, the results say so.
- Open models per role keep a full run at about a cent (Gemma ≈ $0.00003, DeepSeek ≈ $0.0004
  per call, measured 16 Nov).

## As built (17 Nov 2026)

- **Benchmark** (`results/README.md`): LLM agents v2 recovered 9/10 planted edges and promoted 0/10 noise markets. That matches the grid + protocol arm with 1,809 trials instead of 25,200, at $0.34 for 20 studies. v1 recovered 6/10 and is kept, with the reasons for its misses.
- **Round 1 is a code-run baseline:** each planned template's full grid. Models open with textbook values; the agents refine from coverage.
- **The engine seam** (`research_bench/engine.py`). The bench drives a `LocalEngine` or any MCP server with the same tool names: `catalogue`, `dataset_card`, `run_family`, `diagnostics`, `neighbourhood`, `open_holdout`, `protocol`, `seal_log`.
- **The engine owns the success test.** `protocol` returns the text and the bar for the current number of looks. A private engine can judge a family against its own baseline (for example a shipped configuration), with a bar scaled to its own noise.
- **The holdout seal lives in the engine, not the client:** one opening per study, every opening logged.
- **Private use.** A private MCP server over real backtests serves the same names and returns aggregates only. It is not in this repo; per ADR-0001, the real strategies stay outside it.
- **Unusable model output** falls back to the rule policy and is counted in `verdict.agent_failures`.
- **Models per role** were measured on calibration seeds. The research roles stay on DeepSeek V3.2; Gemma alone was 10× cheaper but lost an edge and broke the schema once.

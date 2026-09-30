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

## One contract, two engines — the lab drives the locked IP
The agent loop and the strategies meet at a single seam: the MCP contract
`run_backtest(params, strategy) → metrics`. Because both sides speak it, the **same loop drives
either engine** — only the innermost strategy is swapped.

```
        AGENTIC RESEARCH LAB  (public, readable)
        LangGraph · LLM proposer · judge · memory · HITL
                        │  MCP: run_backtest(params, strategy) → metrics
          ┌─────────────┴──────────────┐
          ▼                             ▼
   SYNTHETIC ENGINE            REAL STRATEGIES  (private, server-side)
   public · toy · clone&run    nifty-weekday / nifty-expiry / sensex-expiry
   what a stranger runs        what runs in production — logic never ships
```

- The three products appear here **by name only** (`list_strategies()`), as synthetic stand-ins that
  differ solely in a public market *profile* (seed, reversion, noise). The real **entry/exit logic is
  proprietary** and served behind this identical contract — an agent host cannot tell which engine it
  drives, nor need to.
- **IP is protected by the contract boundary, not obfuscation** — no compiled blobs. The public repo
  stays fully readable and `clone && run`, which is the stronger interview signal: *the intelligence
  that operates the strategies is right here; only the edge is behind the seam.*
- So the public repo is not a substitute for the real system — it is the **actual orchestration layer**
  of it, with the innermost edge swapped for a stand-in.

## Production mapping
The reference implementation runs the loop in plain Python (workflow-shaped, zero deps). The
production build re-expresses it as a **LangGraph `StateGraph`** for checkpointing, streaming, and
HITL interrupts; the proposer becomes a structured **LLM** call; the evaluator adds an LLM-as-judge
rubric and a regression eval set gated in CI. The control logic is unchanged — see
[ADR-0003](../docs/adr/0003-bounded-autonomy.md).

## As built (2026-09-30)
What actually runs in this repo, today:
- **Plain Python, stdlib, deterministic by default** — the default path imports no LangGraph
  (`research_lab/supervisor.py`, `agents/proposer.py`, `agents/backtester.py`, `agents/evaluator.py`).
- **An optional LLM proposer.** `Proposer(use_llm=True)` swaps the heuristic for a structured
  Claude call; `Supervisor(use_llm=True, context_mode=...)` threads it through. Nothing else in
  the loop changes — the schemas, `verify.py`, the evaluator and the HITL gate are identical
  either way, which is the "one contract" claim above applied to the *agent* rather than the
  engine. The default stays deterministic so a fresh clone still runs with no API key, and LLM
  proposals are clamped into the parameter space before `verify_variant` sees them: the model is
  not trusted to respect the contract. The call goes through `llm_gateway/` (Anthropic, Claude on
  Bedrock, or Ollama via `LLM_PROVIDER`), which validates the reply against a Pydantic schema;
  see [ADR-0008](../docs/adr/0008-provider-routing.md). Needs `pip install -e '.[llm]'` and a
  provider (an API key, AWS credentials, or a local `ollama serve`).
- **`research_lab/verify.py`** adds the deterministic verification hooks this design implies:
  every proposed variant is checked against the declared parameter space *before* it's backtested,
  and every result is checked for NaN/inf/out-of-range *after* — loudly (raises), not silently,
  because a NaN score just never beats the baseline and the loop "succeeds" having learned nothing.
- **`make gate` / `eval/run_gate.py`** is the CI eval-gate described above. It has two arms:
  `--arm stdlib` (the supervisor) and `--arm graph` (`run_graph --no-gate --assert-beats-baseline`);
  CI runs both. On 2026-09-30 both pass at seed 3 (best 36.5 against a 4.9 baseline).
- **`research_lab/experiments/context_study.py`** measures what the proposer's context costs:
  the same loop under three context constructions (full history / best-so-far / compacted
  summary), reporting input tokens against best score. Across three seeds, compaction held 95%
  of the full-history score for 46% of the input tokens; whether full history genuinely beats
  compaction is *not* settled by that data (the per-seed spread exceeds the gap). Raw runs and
  the honest reading are in `results/`.
- **The LangGraph `StateGraph` arm is built** (`research_lab/graph.py`, `run_graph.py`: SQLite
  checkpoint, a real `interrupt()` human gate, resume from another process). The stdlib loop above
  stays the spec and the zero-dependency default. The graph reseeds its proposer per iteration
  (a live RNG cannot be checkpointed), so the two arms are each deterministic but explore
  different variant sequences for the same seed. Backtests run serially in one node (no `Send`
  fan-out). See [ADR-0007](../docs/adr/0007-langgraph-primary-orchestrator.md).
- **The MCP contract is exercised, not just served.** `--engine mcp` (either CLI) sends every
  backtest over MCP stdio through `research_lab/mcp_client.py`; `research_lab/tests/test_mcp.py`
  asserts the results are byte-identical to the in-process engine for every named strategy.
- **Persistent memory** (`--memory sqlite`, `research_lab/memory_store.py`): episodic, semantic
  and procedural layers over one SQLite file; the heuristic explorer samples from learned priors
  half the time. See [03](03-memory.md) and [ADR-0009](../docs/adr/0009-persistent-memory.md).
- **An enforced budget** (`research_lab/budget.py`, `--max-usd` / `--max-llm-calls` on both arms):
  checked before every model call; once spent, the loop stops with `stop_reason="budget"`.
- **An LLM-as-judge, veto-only** (`research_lab/agents/judge.py`, opt-in with `--judge` on either
  CLI). The evaluation ladder is `verify.py` (deterministic) → Evaluator score (arithmetic,
  primary) → Judge veto (LLM) → human gate. When the loop is about to stop with a `promote?` best,
  the judge reviews the top-3 `promote?` candidates against a fixed rubric (does the rationale
  predict the direction the metrics moved? does the edge hinge on a parameter within 2% of a
  `PARAM_SPACE` bound? is the trade count large enough to trust?) and returns a schema-validated
  `JudgeVerdict`. `rationale_consistent=false` or `overfit_risk="high"` downgrades `promote?` to
  `hold`; in the graph arm, if the best is no longer `promote?` the run finishes without pausing.
  What it is **not** allowed to do: re-score, re-rank, upgrade any verdict, promote anything, or
  block a run. A failure (no key, provider error, invalid JSON twice, budget exhausted) is an
  abstention that leaves the verdict unchanged and is counted (`judge: N calls · V vetoes · A
  abstained`). Judge calls share the run's `Budget`. Trials already written to memory keep the
  Evaluator's verdict; the veto changes the ranked output and the gate, not the memory.
- **Judge eval** (`make judge-eval`, `eval/judge_eval.py`): 12 hand-labelled golden cases in
  `eval/datasets/judge_golden.jsonl` (params and metrics are real engine output; rationales and
  labels are hand-written), pass at ≥ 9/12. It needs a provider key and is **not** run in CI;
  CI runs only `--fake`, which checks the harness, not the model. No real-model agreement number
  has been recorded yet, so none should be quoted.
</content>
- **Not built:** parallel backtests (the Goal above says "in parallel"; today every backtest runs
  serially), token streaming from the graph, a Postgres checkpointer (a paused thread can only be
  resumed on the host that holds the SQLite file), walk-forward validation, and a measured
  real-model agreement rate for the judge.

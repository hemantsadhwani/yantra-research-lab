# ADR-0007 — LangGraph StateGraph is the primary orchestrator; the stdlib supervisor stays the spec

**Status:** accepted · 2026-09-29

## Context
ADR-0003 said the production build would re-express the bounded loop as a LangGraph
`StateGraph` for checkpointing and human-in-the-loop interrupts. Until WP1 that was a sentence:
the only loop was `research_lab/supervisor.py`, and its "human gate" was a line of printed text.
A human gate that does not stop the process is not a gate.

## Decision
- **The `StateGraph` arm is the primary orchestrator** (`research_lab/graph.py`,
  `research_lab/run_graph.py`). Nodes: `baseline → propose → backtest_all → record`, then
  `propose` again, or `judge` (with `--judge`), `gate` or `finalize`. Each node is a thin adapter
  over the existing agents and `verify.py`, so no agent logic is duplicated.
- **The stdlib supervisor stays.** It is the spec the graph must match, the zero-dependency
  path a fresh clone runs, and the control arm when the two are compared. It is not deprecated.
- **`SqliteSaver` checkpointer** at `.yantra/checkpoints.sqlite` (or `$RESEARCH_CHECKPOINT_DB`).
  State is plain JSON, so any checkpointer round-trips it with no custom serialisers.
- **`interrupt()` before promotion.** `gate` stops the run; only
  `run_graph --resume <thread> --decision approve|reject` continues it. The resume can come from
  another process. `approval` is set only by that resume.
- **Per-iteration reseeding.** A live RNG cannot be checkpointed, so `propose` rebuilds the
  proposer from state and seeds it with `hash((seed, iteration))`. `hash` of an int tuple is
  stable across processes, so a resumed run reproduces exactly.

## Why
- Checkpoint plus interrupt is the smallest change that turns "promote?" from a printed string
  into a real stop: the process can exit, and nothing promotes until a named decision arrives.
- Keeping the stdlib loop keeps "clone it and it runs, no install" true, and gives the graph
  something to be tested against.

## Trade-offs
- **The two arms produce different variant sequences for the same seed.** The supervisor
  holds one RNG for the whole run; the graph reseeds per iteration. Both are deterministic,
  both are eval-gated (`python -m eval.run_gate --arm both`), and at seed 3 both land at score
  36.5 against a 4.9 baseline, via different variants (`v007` vs `v023`). Any quoted number has
  to say which arm produced it.
- **Backtests run serially in one `backtest_all` node, not fanned out with `Send`.** The
  synthetic engine takes milliseconds per variant, so parallel branches would add reducer and
  ordering complexity for no measurable gain, and one node keeps the checkpoint small and the
  ranking order deterministic. `Send` becomes worth it when a backtest is slow: the private
  engine, or walk-forward windows.
- **SQLite checkpoints live on one host.** A paused thread cannot be resumed from a different
  machine. The scale path is LangGraph's Postgres checkpointer, a constructor swap in
  `default_checkpointer()`. Not built.

## Import boundary
Only `graph.py` and `run_graph.py` import langgraph. `run.py`, `supervisor.py`, `memory.py`,
`schemas.py`, `verify.py` and `budget.py` never import langgraph, mcp, pydantic, anthropic,
fastembed or logfire. `tests/test_smoke.py::test_stdlib_path_never_imports_langgraph` and
`test_budget_and_stdlib_run_never_import_optional_sdks` check this in a fresh subprocess, and
the CI `core` job installs no extras, so a leak fails there as an `ImportError` too.

## As built (2026-09-30)
`research_lab/tests/test_graph.py` covers: beats baseline at seed 3, deterministic across runs,
pauses at the gate and resumes with approval, resume survives a process restart, reject never
promotes, every proposal evaluated once, the graph runs over MCP. Try it:
`make demo-graph`, then `make resume THREAD=<id> DECISION=approve`.

# ADR-0009 — Persistent memory: three layers over one SQLite file, promotions human-only

**Status:** accepted · 2026-09-30

## Context
`research_lab/memory.py` holds the current run's best-so-far and trial log, and forgets both
when the process exits. So "remember what worked" meant "within one run". ADR-0003 named the
swap (episodic memory → semantic + procedural over SQLite); WP3 builds it.

## Decision
- **One SQLite file** (`.yantra/research.sqlite`, or `$RESEARCH_MEMORY_DB`), stdlib `sqlite3`,
  tables `runs`, `trials`, `promotions`, `priors`. `SqliteMemory` (`research_lab/memory_store.py`)
  has the same duck-typed surface as `Memory`, so the supervisor, the graph and both proposers
  take it unchanged. Opt in with `--memory sqlite` on either CLI.
- **Episodic:** every trial of every run is written through. The `Memory`-compatible methods
  are scoped to the current run, so a run's exploit step behaves the same whichever store
  backs it.
- **Semantic:** `recall_similar(text, k)` ranks this strategy's stored trials, across runs, by
  cosine similarity to an embedding of `rationale + params`. Up to three recalled trials go into
  the LLM proposer's `compacted` context.
- **Procedural:** `priors()` is a per-parameter `[min, max]` box over the top quartile of
  *previous* runs' trials (none below 5 prior trials), computed once per run. The heuristic's
  explorer samples inside it half the time and from the full space otherwise.
- **Embedder:** fastembed `BAAI/bge-small-en-v1.5` (384-dim) with the `memory` extra; otherwise,
  or with `YANTRA_EMBEDDER=hashed` (tests, CI), a deterministic 256-dim hashed bag-of-words.
  Each stored vector is tagged with its embedder, and recall only compares like with like.
- **Promotions are human-only.** `record_promotion(..., decided_by="human")` is the only writer,
  the graph calls it from `finalize` only after a human resumed the gate with `approve`, and the
  table has `CHECK (decided_by = 'human')`, so even a code bug cannot insert a machine promotion.

## Why
- Priors narrow exploration toward past winners without closing it off: half the samples still
  cover the full space, so a bad prior cannot trap the loop. Taking priors from previous runs
  only keeps a run's own proposals reproducible under its seed.
- A Python-loop cosine over hundreds to low thousands of rows takes milliseconds. `sqlite-vec` is
  another native dependency, and it is not worth adding until the trial count makes the linear
  scan measurably slow.
- The graph opens and closes the store inside each node and never puts a connection in state,
  so checkpoints stay JSON.

## Trade-offs
- **The hashed embedder captures lexical overlap, not meaning.** Heuristic rationales are
  near-identical strings, so for heuristic runs recall mostly keys on the params summary.
  fastembed fixes that at the cost of a roughly 0.1 GB model download on first use.
- **Memory keeps the pre-veto verdict.** `record` writes each iteration's trials before the
  judge runs, so a judge veto changes the ranked output and the gate (state) but not what is
  stored (memory). Memory records what the arithmetic evaluator decided, and the judge's opinion
  does not flow back into the priors.
- **No evidence yet that priors help.** In one seed-3 demo, the second run's best came from the
  learned box. That is one anecdote, not a result. Showing it needs a multi-seed comparison
  like the context study, which has not been run.

## As built (2026-09-30)
Covered by `research_lab/tests/test_memory_store.py` (persistence across instances, priors
below 5 trials, top-quartile box, second-run explorer inside priors, recall, promotion only on
human approval, in-process memory unchanged). Demo: `make demo-memory` runs the graph twice over
one store; the second header reads `priors from 1 prior run`.
`tests/test_smoke.py::test_memory_modules_stay_stdlib` keeps fastembed out of the import path.

# 03 · Memory — episodic / semantic / procedural

Memory is what makes each research run smarter than the last, without re-deriving what's known.

## The three kinds
| Kind | Holds | In the loop |
|---|---|---|
| **Episodic** | every trial of every run — variant, params, score, verdict, rationale | this run's best-so-far steers the exploit step; the full log feeds the LLM context |
| **Semantic** | an embedding of each trial's rationale + params | `recall_similar(text)` pulls past trials that read like the current best into the LLM's `compacted` context |
| **Procedural** | a narrowed sampling box learned from past winners | the heuristic explorer samples inside it half the time; the `compacted` context states it in one line |

## Design
- **In-process (default):** `research_lab/memory.py` — episodic best-so-far plus the current
  run's trial log. The proposer perturbs the top variant (exploit) while keeping ≥1 fresh
  sample per batch (explore). Deterministic, dependency-free, forgets everything at run end.
- **Persistent (`--memory sqlite`):** `research_lab/memory_store.py` — `SqliteMemory`, the same
  duck-typed surface (`observe`, `best_*`, `trials`, `trial_count`) over one stdlib-`sqlite3`
  file (`.yantra/research.sqlite`, or `$RESEARCH_MEMORY_DB`). Tables: `runs`, `trials`,
  `promotions`, `priors`.
  - The Memory-compatible methods are scoped to the current run, so a run's exploit step
    behaves exactly as it would in-process. What crosses runs is recall and priors.
  - **Priors:** per parameter, `[min, max]` over the top quartile (by score) of *previous*
    runs' trials for the same strategy; `None` below 5 prior trials. Computed once per run
    so the box cannot shift mid-run. `refresh_priors()` (run end) materialises the box over
    all runs into the `priors` table for inspection.
  - **Recall:** cosine similarity in a Python loop over stored float32 vectors, filtered to the
    strategy and to vectors from the embedder in use. Embedder: fastembed
    `BAAI/bge-small-en-v1.5` when the `memory` extra is installed, otherwise (or with
    `YANTRA_EMBEDDER=hashed`, as in tests/CI) a deterministic 256-dim hashed bag-of-words.
    Every row records which embedder produced it.
  - **Promotions:** written only by `record_promotion(..., decided_by="human")`, which the
    graph calls from `finalize` after a human resumed the gate with "approve". A table
    `CHECK` constraint rejects any other `decided_by`.

## Decisions (ADR lens)
| Decision | Why / trade-off |
|---|---|
| Plain SQLite + Python-loop cosine, not `sqlite-vec` yet | zero extra deps; at hundreds–thousands of trials a linear scan is milliseconds. `sqlite-vec` is the upgrade when it isn't |
| Priors as a box, sampled half the time | narrows exploration toward past winners without collapsing it: the other half still samples the full space, so a bad prior can't trap the loop |
| Priors from *previous* runs only | a run can't bootstrap off its own trials, and its own proposals stay reproducible under a seed |
| `everything` / `best_only` contexts ignore cross-run memory | keeps the context study comparable whichever store backs the run |
| Externalized memory (not in-context) | agents stay stateless/restartable; the graph opens and closes the store inside each node, never in checkpointed state |

## Cost / latency
Memory reads/writes are cheap and off the hot path. With fastembed, the first use downloads the
model (roughly 0.1 GB) once; embedding a trial is then a few ms. The hashed embedder is free.

## As built (2026-09-30) — and what is not claimed
Decision record: [ADR-0009](../docs/adr/0009-persistent-memory.md).
- Built: everything above, covered by `research_lab/tests/test_memory_store.py`; demo with
  `make demo-memory` (two graph runs; the second one's header reads `priors from 1 prior run`).
- The hashed embedder captures lexical overlap, not meaning. Heuristic rationales are
  near-identical strings, so for heuristic runs recall is mostly driven by the params summary.
- No measurement yet that priors improve outcomes across seeds. One seed-3 demo run beating
  another is an anecdote, not evidence; it needs a multi-seed comparison like the context study.
- **Memory keeps the pre-veto verdict.** The graph's `record` node writes each iteration's trials
  before the optional judge runs, so a judge veto (`promote?` → `hold`) changes the ranked output
  and the human gate, not the stored trial or the priors computed from it.
- **Promotions come only from the graph arm.** The stdlib arm has no interrupt, so a
  `python -m research_lab.run --memory sqlite` run writes trials and priors but never a promotion.
- **Not built:** `sqlite-vec` (not needed at this row count), Postgres/OpenSearch-backed memory, and
  any automatic pruning or decay of old trials.

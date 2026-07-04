# eval/ — the evaluation harness (CI eval-gate)

Evaluation is where most RAG/agent systems quietly regress, so it's gated in CI (not optional).

- **`run_gate.py`** *(live)* — agent-loop regression: the research loop must still discover a
  variant that **beats the baseline** (`promote?`), else CI blocks the dev→prod promotion.
- **RAG golden** *(next)* — score chatbot answers vs `knowledge_base/eval_sets/rag_golden.jsonl`.
- **Red-team leak-rate** *(next)* — run `redteam_leak.jsonl`; assert IP/PII leak-rate ≈ 0.

Same backtest-parity discipline the trading bot uses, applied to the pipeline itself.
</content>

# eval/ — the evaluation harness (CI eval-gate)

Evaluation is where most RAG/agent systems quietly regress, so it's gated in CI (not optional).

- **`run_gate.py`** *(live)* — agent-loop regression: the research loop must still discover a
  variant that **beats the baseline** (`promote?`), else CI blocks the dev→prod promotion.
- **`redteam.py`** *(live)* — guardrail red-team, two modes:
  - offline (`python -m eval.redteam`): 26 attacks + 20 benign controls against the input
    guardrails; reports block rate and false positives.
  - end to end (`python -m eval.redteam --live`): the FastAPI app in-process with a
    `FakeProvider` scripted to **leak on purpose**; measures `leak_rate` (leaked answers that
    reached the user / attacks) with the output filter on and off (`YANTRA_OUTPUT_FILTER=0`).
    A leak is judged against the scripted leak strings (ground truth), not the filter's own
    regex. Current: leak_rate 0/32 with the filter on, 6/32 off (the 6 evasive prompts that
    pass the input guardrails); with input guardrails bypassed the filter alone stops 26/26.
    Caveat: the leaks are hand-written shapes, so this measures the filter's coverage of
    those shapes, not a real model's creativity.
- **RAG golden** *(next)* — score chatbot answers vs `knowledge_base/eval_sets/rag_golden.jsonl`.

Same backtest-parity discipline the trading bot uses, applied to the pipeline itself.
</content>

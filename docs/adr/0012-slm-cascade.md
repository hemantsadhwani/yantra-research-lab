# ADR-0012: SLMs route and score; frontier models write

Date: 2026-09-30 · Status: accepted

## Context

Every model call in the repo went to one tier: a frontier model (Haiku 4.5) for enrichment,
vision captions, the judge and the LLM proposer. Some of those calls do not need a frontier
model. They are small, closed-set decisions: which bucket, which route, pass or fail. A frontier
model is paid per call and sends the content to a vendor. A small local model is free per call
and keeps the content on the machine. Code is cheaper still, when a rule is good enough.

The ingestion DAG has a clean first case. After `parse`, each page is text, table-heavy,
figure-heavy, scanned or mixed. That label decides which expensive step a page needs (OCR,
vision captioning, or neither). The labels are also free: the parser already found the tables,
images and figure captions.

## Decision

1. **Three tiers behind one protocol.** `LayoutClassifier.classify(features) -> decision` has
   three backends, chosen by `YANTRA_LAYOUT_BACKEND`:
   - `rules` (default): code over cheap parser counts. Offline, $0.
   - `slm`: a local model (Ollama `qwen2.5:1.5b`) through `llm_gateway`, strict Pydantic output.
   - `frontier`: Haiku 4.5 through `llm_gateway`, same schema, same prompt.
   The escalation order is code, then SLM, then frontier.
2. **SLMs decide and score; frontier models write.** Closed-set outputs (a label, a route, a
   score, a veto) are SLM candidates. Open-ended text (summaries, captions, proposals with a
   rationale) stays on a frontier model. The router never writes anything.
3. **Swap-in rule.** A cheaper tier replaces a dearer one only after it agrees with the dearer
   tier on at least **95%** of a held-out set, measured by `eval/layout_eval.py` (the
   "agreement with frontier" column). Accuracy against labels is reported too, but agreement
   is the gate, because in production the frontier tier is the reference, not a rule.
4. **No silent fallback.** If the chosen tier is unavailable (Ollama down, no key) the router
   raises. A router that quietly drops to another tier makes its own eval meaningless.
5. **Free labels first, frontier-as-teacher designed.** The kata's teacher is
   `ingestion/layout_labels.derive_label`, a deterministic rule over the parser's output. The
   production shape is: the frontier model labels a sample, that becomes the SFT set, a small
   model is LoRA-tuned on it, and CI blocks a student that drifts below the swap-in rule.
   That flow is designed, not run (it would cost money and needs no new code to describe).
6. **Advisory by default.** The DAG records `layout` per page and changes nothing else; the
   existing outputs are byte-identical (test in `ingestion/tests/test_layout.py`).
   `INGEST_LAYOUT_GATE_CAPTION=1` opts in to captioning only the pages the router marked.

## Why a privacy tier

The SLM tier is also the privacy tier. A page from a private document can be routed by a model
on the same host, so the content never leaves it. Only pages that need a frontier model (to
write a caption or a summary) cross the boundary. For regulated content, "the router never
sends the page anywhere" is a stronger property than any vendor contract.

## Measured so far

- `python -m eval.layout_eval --fake`: the `rules` row is real (0.99 on 215 real parsed arXiv
  pages, where always answering `text` gets 0.83; 0.90 on the 200-page synthetic set). The
  `slm` and `frontier` rows are scripted FakeProviders: they prove the harness, not models.
  Frontier cost at Haiku 4.5 list price: about $0.21 to $0.28 per 1,000 pages (a floor).
  See `results/layout_2026-09-30.md`.
- `slm_regime_classifier/distill_layout.py`: CPU LoRA on SmolLM2-135M-Instruct against the
  free labels. On 60 held-out examples: base 0.00, tuned 0.87 with class-balanced batches
  (majority baseline 0.57; the rules backend 0.92), about 1.3 s per page on the dev Mac's CPU.
  An unbalanced first run collapsed to the majority class. Both runs hit the 25-minute cap.
  See `slm_regime_classifier/adapter_card.md` and `results/distill_2026-09-30.md`.

## Not built

- A real `slm` or `frontier` eval row (Ollama is not installed on the dev Mac; the frontier row
  costs money).
- A vLLM serving benchmark (throughput, p95 under load).
- GPU QLoRA (4-bit). `--qlora` exists in the script and refuses to run without CUDA.
- A DocLayNet-style block-level layout model (boxes per region from pixels). This router is
  page-level and reads parser features, not pixels.
- Routing for the other closed-set calls (the judge's veto, the quality gate).

## Consequences

- Default behaviour, CI and the daily cron are unchanged: `rules` is offline and advisory.
- A model tier can be tried with one env var, and its eval uses the same table and columns.
- The swap-in rule gives an interview-ready answer to "when would you fine-tune?": when a
  closed-set call is frequent enough that per-call cost or data egress matters, and a small
  model clears 95% agreement with the frontier model on held-out data.

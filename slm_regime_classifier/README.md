# slm_regime_classifier/ — the fine-tuning use case (justified, not a toy)  ·  Tier 2

Distills a frontier regime-classifier into a **quantized on-prem SLM** so the trading bot's
**intraday gate** becomes affordable, low-latency, and no-egress. The senior point: the *daily*
gate stays on the frontier API (fine-tuning wouldn't amortize) — knowing where fine-tuning pays.

**Layout:** `distill/` (Claude labels a historical corpus → synthetic SFT set) · `finetune/`
(QLoRA SFT a Qwen SLM, 4-bit) · `serve/` (vLLM/Ollama, <50 ms) · `eval_gate/` (SLM-vs-teacher
tolerance; CI blocks a regressing model).

ADR: *fine-tune vs RAG vs prompt* — fine-tune to **distill** for cost/latency/compliance, not for
knowledge. See [architecture/07-model-routing-finetune.md](../architecture/07-model-routing-finetune.md).
</content>

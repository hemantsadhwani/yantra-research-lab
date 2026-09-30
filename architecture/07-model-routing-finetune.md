# 07 · Model routing & the fine-tuning use case

## Model routing — avoid lock-in, control cost
An **LLM gateway** (e.g. LiteLLM) fronts every model call:
- **Frontier models** (Claude via Bedrock) for the hardest reasoning.
- **Open-weight models** (Qwen/Llama via vLLM/Ollama) for cost, on-prem, and compliance.
- **Prompt caching** on long, stable system prompts.
- **Route by task difficulty** — cheap model first, escalate only when needed.

One sentence answers *why / cost / compliance / latency / lock-in* at once: *OSS orchestration +
best-in-class paid models for hard reasoning + open-weight for cost/compliance, routed by
difficulty, keeping the LLM off any latency-critical path.*

## The fine-tuning use case — justified, not a toy
A regime **classifier** turns market context into a small structured label. A frontier API is fine
for a **low-frequency** call, but a **high-frequency** variant hits three walls:

| Wall | Why a fine-tuned SLM wins |
|---|---|
| **Cost** | a frontier call at high frequency across a session is uneconomic; an SLM is ~zero marginal cost |
| **Latency** | a frontier round-trip is too slow for a tight checkpoint; a quantized SLM classifies in <50 ms locally |
| **Compliance** | keeps sensitive market context **on-prem**, no data egress |

**Solution — the full lifecycle, all justified:**
```
frontier model labels a historical corpus  (teacher → synthetic SFT dataset)
   → QLoRA SFT a small open model (4-bit)
   → quantize + serve (vLLM/Ollama, <50 ms, on-prem)
   → EVAL-GATE: SLM must match the teacher within tolerance before it ships (CI-blocked)
   → deploy behind the gateway, fail-open to a deterministic rule
```

## The senior point — knowing where *not* to fine-tune
The same system makes **opposite** decisions and can defend both: the **low-frequency** path stays
on the frontier API (fine-tuning would never amortize); only the **high-frequency** path gets the
SLM. That is the textbook **fine-tune vs RAG vs prompt** call — *fine-tune to **distill** for
cost/latency/compliance, not for knowledge* — and knowing where it *doesn't* pay is the senior signal.

## As built (2026-09-30)
**The gateway is built; routing and the SLM are not.** Decision record:
[ADR-0008](../docs/adr/0008-provider-routing.md).

| Piece | Status |
|---|---|
| Provider seam (`llm_gateway/`) | **Built.** One `Provider.complete(...)` protocol; `LLM_PROVIDER=anthropic\|bedrock\|ollama` picks Claude direct (`claude-haiku-4-5`), Claude on AWS Bedrock (same SDK, `AnthropicBedrock` client), or a local Ollama model (stdlib HTTP, default `qwen2.5:7b-instruct`). Used by the research proposer, the judge and the chatbot backend |
| Structured output | **Built.** A ladder per call: `native` (`messages.parse`) → `json_schema` (`output_config`) → `prompt` + one repair round-trip; the rung that held is recorded on every response |
| Prompt caching | **Built** on the stable system prompt (`cache_system=True`), for the chatbot, the proposer and the judge |
| Cost accounting | **Estimates only.** One list-price row (Haiku 4.5) in `llm_gateway/pricing.py`, applied to Bedrock ids too; Ollama is $0; unknown models estimate $0 with a warning. Feeds the enforced per-run budget (`research_lab/budget.py`) |
| LiteLLM proxy | **Not built.** A thin adapter is enough for three providers in one process; a proxy is the Phase 2 answer once several services share keys and spend limits |
| Route by task difficulty | **Not built.** Each task (propose, judge, chat) uses one configured model. Nothing escalates from a cheap model to a stronger one, and nothing has yet measured where the cheap model falls short |
| Frontier ↔ open-weight split | **Selectable, not routed.** Ollama works as a drop-in provider (`make demo-ollama`), but choosing it is a human's environment variable, not a policy |

**Deployment caveat.** The backend code calls the gateway since WP4. As of 2026-09-30 the live
Fly app still serves the pre-WP4 build (its `/api/metrics` has no `llm` key), so the deployed
chatbot is still the direct-SDK version until the next deploy.

**SLM status:** not built. The former `slm_regime_classifier/` placeholder (a README only) was
removed; its design now lives in [ROADMAP.md](../ROADMAP.md). The `distill/ finetune/ serve/
eval_gate/` layout it described was never written as code. The fine-tuning lifecycle above is the
target design, not a built artifact.

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
</content>

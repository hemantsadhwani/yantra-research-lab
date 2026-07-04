# chatbot/ — RAG chatbot with dual IP + PII guardrails  ·  Tier 1→2

Answers questions about the platform's methodology and general quant knowledge, over a
role-scoped corpus, while **provably refusing to leak proprietary strategy IP** *and*
**protecting user PII**.

**Dual guardrail mandate**
- **IP:** strategy parameters/edge are kept **out of the retrievable index** (defense in depth) + a refusal policy.
- **PII:** redaction in prompts/logs + **RBAC tenant isolation** (one user never sees another's data). DPDP-aware.

**Planned layout**
```
chatbot/
  retrieval/        hybrid dense + BM25 + visual; contextual retrieval; reranker
  guardrails/       refusal policy · PII redaction · injection detection · rbac.py
  redteam_eval/     "extract the strategy" + "extract PII" attack sets → leak-rate metric
  api.py            FastAPI retrieval endpoint
```
Proof: hand an interviewer the bot, invite a jailbreak, show leak-rate ≈ 0.
See `../job_profile/ai_enginerring/design_context.md` §2, §8.
</content>

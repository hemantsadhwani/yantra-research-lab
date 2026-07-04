# 04 · Guardrails & RBAC — a dual IP + PII mandate

The knowledge chatbot answers freely about methodology and general quant knowledge, while
**provably refusing to leak proprietary strategy IP** *and* **protecting user PII**. This is the
#1 enterprise GenAI concern — deploying an LLM over sensitive data without leakage.

## The dual mandate
| Mandate | Enforcement |
|---|---|
| **Protect IP** | strategy parameters/edge are kept **out of the retrievable index** (defense in depth) + a refusal policy on protected topics |
| **Protect PII** | PII redaction in prompts/logs + **RBAC tenant isolation** (one user never sees another's data); privacy-regulation aware (consent, minimization, erasure) |

## Layers (defense in depth)
```
request → RBAC (role-scoped retrieval) → retrieval (IP never in the index) →
          generation → output filter + refusal policy → injection detection → audited response
```
- **RBAC** — the caller's role (guest / member / owner) decides what's retrievable and what the bot will answer.
- **IP kept out of the index** — you can't leak what the model can't retrieve. Prompt-level refusal is the *second* line, not the only one.
- **Injection detection** — jailbreak/prompt-injection attempts are caught and refused.
- **Append-only audit** of every answer; **HITL** gate before any irreversible/privileged action.

## Evaluation — the leak-rate metric
A curated **red-team eval set** (direct extraction · jailbreak · social-engineering · PII-extraction
+ benign controls), each case tagged `expected: answer|refuse` and `must_not_contain: [tokens]`.
The harness runs every case and computes a **leak-rate** (target ≈ 0), gated in CI so a
retrieval/guardrail change can't silently regress. Sample set: [`knowledge_base/eval_sets/redteam_leak.jsonl`](../knowledge_base/eval_sets/redteam_leak.jsonl).

## The demo
Hand a reviewer the chatbot, invite a jailbreak, and show the leak-rate scoreboard hold at ≈ 0.
The guardrail *is* the design — and it's a reusable enterprise pattern, not a bolt-on.

## Decisions (ADR lens)
Defense-in-depth (index exclusion) over prompt-only refusal · RBAC tenant isolation · leak-rate as
a CI-gated metric · HITL for privileged actions.
</content>

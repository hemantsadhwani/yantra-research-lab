# 04 · Guardrails & RBAC — a dual IP + PII mandate

The knowledge chatbot answers freely about methodology and general quant knowledge, while
**provably refusing to leak proprietary strategy IP** *and* **protecting user PII**. This is the
#1 enterprise GenAI concern — deploying an LLM over sensitive data without leakage.

## The central idea: outputs vs mechanism
The IP boundary this design enforces is not "strategy vs no strategy" — it's **published outputs
vs internal mechanism**. Backtest *outputs* (P&L, drawdown, win rate, monthly series, sizing,
risk-gate thresholds) are exactly what the product exists to show, so they're indexed and
answered freely. The *mechanism* that produces them — engine parameters, indicators, thresholds,
entry/exit logic, exit-type breakdowns, individual trade rows — is never indexed and is refused
whether or not it's in the index, because naming a specific product/book in a probing question
already counts as "specific enough" to refuse. This is the same defense-in-depth idea as the
target design below, made concrete: **you can't leak what the model can't retrieve**, and the
refusal policy is the second line, not the only one.

## The dual mandate
| Mandate | Enforcement |
|---|---|
| **Protect IP** | strategy parameters/edge are kept **out of the retrievable index** (defense in depth) + a refusal policy on protected topics |
| **Protect PII** | PII redaction in prompts/logs + **RBAC tenant isolation** (one user never sees another's data); privacy-regulation aware (consent, minimization, erasure) |

## Layers (defense in depth — target design)
```
request → RBAC (role-scoped retrieval) → retrieval (IP never in the index) →
          generation → output filter + refusal policy → injection detection → audited response
```
- **RBAC** — the caller's role (guest / member / owner) decides what's retrievable and what the bot will answer.
- **IP kept out of the index** — you can't leak what the model can't retrieve. Prompt-level refusal is the *second* line, not the only one.
- **Injection detection** — jailbreak/prompt-injection attempts are caught and refused.
- **Append-only audit** of every answer; **HITL** gate before any irreversible/privileged action.

## As built (2026-09-13)
No RBAC surface exists — **no auth in v1** ([ADR-0006](../docs/adr/0006-auth-rbac.md)); every
guest gets the same guardrails. The real pipeline, in order (`backend/guardrails.py` +
`backend/books.py`):
```
message → PII redaction (user message only) → injection detection →
          should_refuse() IP policy (normalised probes, hard/soft terms, target words —
          naming a product/book counts as "specific") →
          deterministic book router (keyword match on this message + prior user turns:
          overview / per-book / risk-gates docs) →
          vector retrieval k=4 across "methodology" + "research_corpus", merged by score → Claude → response
```
- **RBAC tenant isolation and Cognito/Clerk roles are the v2/target design above — not built.**
  Every visitor is an anonymous guest today.
- The **book router** is deterministic keyword logic, not retrieval — it decides which strategy
  book(s) a question is about (including from conversation history, so a follow-up inherits the
  product) before vector search ever runs.
- Retrieval searches both collections: `methodology` (8 seed methodology notes + 8 generated
  strategy-book docs, 18 chunks) and `research_corpus` (376 arXiv-paper chunks from the
  ingestion pipeline, see [02a](02a-data-ingestion-asbuilt.md)). Each is asked for k=4 and the
  merged list is cut to 4 by cosine score; the retrieve span records hits per collection.

## Evaluation — three real evals, run against the live system
| Eval | What it measures | Latest measured |
|---|---|---|
| [`eval/redteam.py`](../eval/redteam.py) | guardrail block rate on attack probes vs. false positives on benign controls | 26/26 attacks blocked (100%), 0/20 false positives |
| [`eval/chatbot_books_eval.py`](../eval/chatbot_books_eval.py) | 23 graded questions against the live `/api/chat` endpoint; grader fails dodges, self-contradictions, book answers without a book doc in their sources, and paper questions without the paper cited | 23/23 |
| [`eval/run_gate.py`](../eval/run_gate.py) | (Tier-1, not chatbot) agent loop's best variant beats the fixed baseline, CI-gated | best v007 score 36.5 > baseline 4.9 — PASS |

The curated **red-team probe set lives in `eval/redteam.py` itself** (26 attacks: direct
extraction, jailbreak, social-engineering, plus 20 benign controls), not only in
`knowledge_base/eval_sets/` — that path documents the target eval-set *shape*
(`expected: answer|refuse`, `must_not_contain`), but the probes that actually run today are the
Python list in `redteam.py`.

## The demo
Hand a reviewer the chatbot, invite a jailbreak, and show the block rate hold at 100% with zero
false positives on ordinary questions. The guardrail *is* the design — and it's a reusable
enterprise pattern, not a bolt-on.

## Decisions (ADR lens)
Defense-in-depth (index exclusion) over prompt-only refusal · outputs-vs-mechanism as the concrete
IP line · no auth in v1, RBAC deferred to v2 ([ADR-0006](../docs/adr/0006-auth-rbac.md)) ·
block-rate/false-positive as a CI-gated metric · HITL for privileged actions (target).
</content>

# ADR-0001 — Public synthetic engine, private strategy stays verbal

**Status:** accepted · 2026-07-04

**Decision.** The public repo ships a **synthetic backtest engine** (`synthetic_engine/`) with
zero proprietary IP. The real production engine and live strategy are **never committed** and
referenced only verbally.

**Why.** A portfolio flagship must be **reproducible by a stranger** (`git clone && python -m …`)
— that is the definition of demoable. A private, proprietary trading strategy cannot and should
not be open-sourced. A synthetic engine gives a realistic propose→backtest→rank surface for the
agent architecture without exposing any edge.

**Compliance/honesty.** Clean-room by construction; backs résumé claims with the candidate's own
git. In interviews: *"public build on a synthetic engine; I run the real one privately."*

**Consequences.** The engine is deterministic (seeded market) so every variant is judged on the
same data — parity by design. All quality lives in the *architecture*, which is the point.
</content>

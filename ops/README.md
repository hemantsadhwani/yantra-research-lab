# ops/ — observability & operations  ·  Tier 2→3

Observability as a **strategy on an OpenTelemetry backbone** (vendor-neutral), fanning out per layer:
- **LangSmith** — agent trajectories / tool calls / tokens (primary debugging lens)
- **Logfire** — Pydantic/FastAPI service traces + structured logs
- **Langfuse** — self-hostable / on-prem (the compliance answer)
- cost/**FinOps** meter · embedding/response **drift** monitor · CloudWatch infra metrics

Pillars: traces · metrics · logs **+ evals · drift**. `observability/` holds the OTel + exporter
config; `scripts/` holds deploy/ops helpers.
</content>

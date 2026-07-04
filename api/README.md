# api/ — backend gateway (FastAPI)  ·  Tier 3

The service the frontend talks to: **Cognito auth + RBAC**, retail registration, simulated-capital
allocation, portfolio state (multi-tenant isolation), and triggers for research runs. Instrumented
with **Logfire** (Pydantic/FastAPI-native) on the OTel backbone. Paper/simulated only — no real money.
</content>

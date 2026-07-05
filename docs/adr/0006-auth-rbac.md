# ADR-0006 — Auth & RBAC: none in v1; Clerk in v2 (Cognito is the AWS-scale target)

**Status:** accepted · 2026-07-05

## Question
How do users authenticate, and how are permissions (RBAC) enforced — at minimal cost and
overhead, without over-building identity before there are any users?

## Decision
- **v1 (the public demo) — no authentication at all.** The MVP is fully public: Landing, Strategy
  Explorer, cached Research Lab, and the guarded chatbot all work for anonymous guests. No login,
  no accounts, no RBAC surface to build or secure.
- **v2 (the retail portal) — Clerk** for authentication **and** RBAC. **Google (social) login** as
  the primary low-friction method; Clerk's built-in **roles + organizations** provide the RBAC layer.
- **AWS Cognito stays the documented scale target** (see
  [architecture/08-deployment-aws.md](../../architecture/08-deployment-aws.md)) — same
  deploy-cheap-document-AWS pattern as the rest of the platform; adopted only if/when the business
  path warrants AWS-native identity.

## RBAC model
| Role | Capabilities |
|---|---|
| **Guest** | browse the site + use the chatbot — no login |
| **Member** | register → allocate *simulated* capital, view **their own** paper-trading dashboard |
| **Admin** | manage the platform |

Plus **tenant isolation** — one member never sees another's data. This feeds the chatbot's PII
guardrail (RBAC-scoped retrieval); see [architecture/04-guardrails-rbac.md](../../architecture/04-guardrails-rbac.md).

## Why Clerk (over Cognito / Auth0 / roll-your-own) for v2
- **Lowest overhead + best Next.js DX** — drop-in components; Google / email / passwordless out of
  the box. Directly answers the "less painful, low-overhead" requirement.
- **RBAC built in** (roles + organizations) — no custom role/permission plumbing to write.
- **~$0 at our scale** — the free tier covers demo / early-business usage (thousands of MAU), and
  Google OAuth itself is free. Cost only appears at real scale.
- **Cognito is AWS-native but has painful DX** — documented as the scale target, not the build-now
  choice. **Auth.js (NextAuth)** is the zero-vendor-lock-in, $0-forever alternative if independence
  ever outweighs DX.

## Consequences
- **Nothing to build for v1** — auth is deferred entirely; the MVP ships without it.
- **v2** adds Clerk to the Next.js frontend, protects member routes/API, gates the member dashboard
  by role, and flows tenant scoping into chatbot retrieval.
- Auth provider keys live in env/secrets, **never** committed.
- Revisit **Cognito** at the PMS / business-scale phase if AWS-native identity is required.

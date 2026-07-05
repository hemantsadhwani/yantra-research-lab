# 08 · Deployment — AWS, monorepo, dev→prod promotion

> **This is the business/scale target.** The *public demo* deploys today on a minimal-cost
> scale-to-zero stack (Vercel + a serverless container + Qdrant/FAISS) — see
> [ADR-0005](../docs/adr/0005-public-demo-deployment.md). Same container lifts to Fargate later.

## Cloud — AWS
| Concern | Service |
|---|---|
| Agents + API | **ECS Fargate** (managed) or **EC2 Graviton** (self-host) |
| Frontend | **S3 + CloudFront** (static SPA) |
| Auth + RBAC | **Cognito** (scale target; demo/v2 uses **Clerk** — see [ADR-0006](../docs/adr/0006-auth-rbac.md)) |
| Artifacts / object store | **S3** |
| Vector DB | Qdrant/Weaviate (self-host) or a managed store |
| Infra metrics | **CloudWatch** |

The SLM endpoint co-locates with the agents; the LLM stays off any latency-critical path.

## Monorepo — one repo, all tiers
One repository for every service/tier — shared contracts move atomically in one PR, one CI
pipeline, one review. See [ADR-0004](../docs/adr/0004-monorepo-and-environment-promotion.md).

## Dev/prod are *environments*, not repos or branches
```
PR/merge → [path-filter: changed?] → lint · test · eval-gate → deploy DEV → (manual approval) → PROD
```
- **Trunk-based:** `main` is always releasable; feature branches → PR → merge.
- **Promotion, not divergence:** CI builds an artifact once, deploys to **dev**, promotes the *same*
  artifact to **prod** on approval. Environment differences live in `infra/environments/{dev,prod}`
  (config/secrets), never in the code.
- **Fast monorepo CI:** path filters run only the affected tier's lint/test/build; a shared
  **eval-gate** blocks promotion on regression (offline↔online parity, applied to CI).

## Decisions (ADR lens)
Monorepo vs polyrepo (atomic contracts, one pipeline) · environments not branches (no dev↔prod
drift) · path-filtered CI (fast at scale) · managed (Fargate) vs self-host (EC2 Graviton) by cost/ops.
</content>

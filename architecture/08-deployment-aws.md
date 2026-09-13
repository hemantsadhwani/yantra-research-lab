# 08 · Deployment — AWS, monorepo, dev→prod promotion

> **This is the business/scale target.** The *public demo* deploys today on a minimal-cost
> stack — **Vercel** (frontend) + **Fly.io** (`yantra-chatbot`, region `sin`, one machine kept
> warm — not scale-to-zero, ~$2/mo) + **Qdrant Cloud** (not local mode) + **Logfire** — see
> [ADR-0005](../docs/adr/0005-public-demo-deployment.md) and [02a](02a-data-ingestion-asbuilt.md).
> Same container lifts to Fargate later.

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

## As built (2026-09-13)
`.github/workflows/ci.yml` implements the shape above, but only the first half actually does
anything:

| Job | Status |
|---|---|
| `changes` (path-filter: core/chatbot/ingestion/slm/frontend) | LIVE |
| `core` — `ruff check .` + `pytest -q`, gated on the `core` path filter | LIVE |
| `eval-gate` — `python -m eval.run_gate`, blocks on regression | LIVE |
| `deploy-dev` | **stub** — `echo "deploy to dev (infra/environments/dev)"` |
| `deploy-prod` | **stub** — `echo "promote same artifact to prod (infra/environments/prod)"`, behind a GitHub `prod` environment approval gate that exists but guards nothing real |

`infra/environments/dev` and `infra/environments/prod` are empty directories — the environment
split described above is a target, not wired.

**Real deploys happen outside this CI file entirely:**
- **Frontend:** Vercel auto-deploys on every push to `main` (its own GitHub integration, not a
  `ci.yml` job).
- **Backend:** manual `fly deploy` from `backend/`, whenever `backend/fly.toml` or app code
  changes. Config changes (e.g. the warm-machine setting) only take effect after a redeploy.
- **Chatbot corpus re-ingest:** also manual — `python ingest.py` run over `fly ssh console`
  against `yantra-chatbot`, since the Dockerfile's build-time ingest never reaches the running
  container (see [02a](02a-data-ingestion-asbuilt.md)).
- **Ingestion pipeline (Tier-3):** the one piece of automated deploy that's real —
  `.github/workflows/ingest.yml` runs on a daily cron and auto-commits the refreshed manifest
  with `[skip ci]`, which Vercel then picks up as a normal push.

The AWS target table above (Fargate/Cognito/CloudWatch) is unchanged as the scale target; nothing
in it is provisioned today.
</content>

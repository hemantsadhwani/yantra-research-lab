# ADR-0004 — One monorepo for all tiers; dev/prod are environments, not repos

**Status:** accepted · 2026-07-04

## Question
Should each tier/service (engine, chatbot, ingestion, SLM, api, frontend, infra) live in its
own repo, and should dev and prod be separate repos or long-lived branches?

## Decision
**One monorepo for everything.** **Dev and prod are *environments*, not repos or branches** —
the same commit is promoted through them by CI/CD.

## Why a monorepo (not polyrepo)
- **Shared contracts.** The Pydantic schemas, the synthetic engine, and the MCP tool defs are
  used by multiple services. In a monorepo a change + its consumers move in **one atomic PR**;
  polyrepo means version-bump dances across repos.
- **One pipeline, one review.** Single CI config, single PR review, single issue tracker — right
  for a solo/small builder shipping fast.
- **Cross-cutting changes are trivial** (rename a schema field → update every consumer in one commit).
- **Strong interview story:** "I run a monorepo with **path-filtered, affected-only CI** and
  **environment promotion**" is exactly the modern platform answer.

## Why dev/prod are environments (not repos / not `dev` & `prod` branches)
- **Trunk-based:** `main` is always releasable. Feature branches → PR → merge to `main`.
- **Promotion, not divergence:** CI builds an artifact once; deploys to **dev**; on approval,
  the *same* artifact promotes to **prod**. Environment differences live in config/secrets under
  `infra/environments/{dev,prod}`, never in the code.
- The anti-pattern we avoid: a long-lived `dev` branch that drifts from `prod` (merge hell,
  "works in dev" surprises).

## How CI/CD stays fast in a monorepo
- **Path filters / affected-only:** a change under `chatbot/` runs the chatbot's lint+test+build,
  not the whole repo. (GitHub Actions `paths:`; graduate to Nx/Turborepo/Bazel if it grows.)
- **Per-service container images**, pushed on merge.
- **A shared eval-gate job** blocks promotion if the agent/RAG regression eval drops (the
  backtest-parity discipline, applied to CI).
- **Env promotion:** merge → CI (lint·test·eval-gate) → deploy **dev** → manual approval → **prod**.

## When we'd reconsider (split a service out)
Different teams with independent release cadence, a hard security/compliance boundary, or the
frontend wanting fully independent deploys. **None apply now** — revisit at team scale.

## Consequences
- `infra/environments/{dev,prod}` holds env config; secrets come from a secrets manager per env.
- CI must use path filters from day one so the repo stays fast as tiers land.
</content>

# ADR-0011: The app layer is packaged for Kubernetes; Fly + Vercel stay the public demo

Date: 2026-09-30 · Status: accepted

## Context

ADR-0005 put the public demo on the cheapest serverless stack that keeps a portfolio app live:
Fly.io for the FastAPI backend, Vercel for the Next.js frontend. That is the right choice for a
one-person, near-zero-cost showcase. It is not how an enterprise platform team runs a service.
Interviewers for platform and architect roles ask for the container and Kubernetes shape of the
app, and "we would containerise it" is a weaker answer than a directory they can read.

## Decision

1. Both app services get production-shaped images: the backend image (already used by Fly)
   moves to `python:3.13-slim` to match the CI matrix; the frontend gets a multi-stage,
   non-root image with Next.js standalone output. `docker-compose.yml` runs both locally, and a
   `private` profile adds Ollama so the chatbot answers with no vendor API.
2. `deploy/k8s/` holds plain kustomize manifests: Namespace, ConfigMap, an example Secret,
   Deployments with startup/readiness/liveness probes, resource requests and limits, a
   non-root security context, Services, a CPU HorizontalPodAutoscaler and an Ingress.
3. `deploy/kind/` plus `make k8s-up` / `k8s-smoke` prove the manifests on a local one-node
   cluster. CI builds both images and renders the manifests on every relevant change.
4. The public deployment does **not** move. Fly and Vercel remain the only production path;
   the Kubernetes layer is verified locally and in CI, never claimed as "running in production".

## Consequences

- Honest claim: "containerised, Kubernetes manifests verified on a local cluster and in CI".
  Never "runs on Kubernetes in production".
- A local cluster tags spans `YANTRA_ENV=staging`, so it cannot pollute the live `/ops` metrics.
- Not built, listed in the README: vault-backed secrets, TLS, NetworkPolicy, PodDisruptionBudget,
  scaling on queue depth or latency (KEDA), Helm chart, Terraform for the cluster itself.

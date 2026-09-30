# deploy/ — containers and Kubernetes for the app layer

The public demo runs on Fly.io (backend) and Vercel (frontend) because that is the cheapest
way to keep a portfolio app live (ADR-0005). This directory is the same app packaged the way an
enterprise platform team would run it: two images, plain Kubernetes objects, a local cluster
to prove they work. ADR-0011 records the decision.

```
backend/Dockerfile      FastAPI backend, built from the REPO ROOT (needs llm_gateway/)
frontend/Dockerfile     Next.js portal, multi-stage, non-root, standalone output
docker-compose.yml      both services locally; `--profile private` adds Ollama (no vendor API)
deploy/k8s/             kustomize: Namespace, ConfigMap, Secret (example), Deployments with
                        startup/readiness/liveness probes and resource limits, Services, HPA, Ingress
deploy/kind/            one-node local cluster config with ingress ports mapped
```

## Local cluster in four commands

```bash
make k8s-up        # kind cluster + ingress-nginx + build both images + load + apply -k
make k8s-smoke     # waits for rollout, curls /health through the Ingress -> {"status":"ok"}
make k8s-status    # pods, services, HPA
make k8s-down      # delete the cluster
```

`make k8s-up` needs Docker (Colima or Docker Desktop), `kind` and `kubectl`. On macOS:
`brew install colima docker kind kubectl && colima start --cpu 2 --memory 4`.
Add `127.0.0.1 yantra.local` to `/etc/hosts` to open http://yantra.local in a browser.

## Verified on 30 Sep 2026 (kind on Colima, macOS)

`make k8s-up && make k8s-smoke`: 2 backend pods and 1 frontend pod Running; `GET /api-backend/health`
through the Ingress returned `{"status":"ok"}`; the frontend returned 200. Rendered objects: 8.

## What is deliberately simple

- Secrets come from `backend-secret.example.yaml` or `kubectl create secret`. A real cluster
  pulls them from a vault (External Secrets Operator, AWS Secrets Manager). Not built.
- No TLS on the local Ingress. Production terminates TLS at the load balancer or cert-manager.
- `YANTRA_ENV=staging` in the ConfigMap: only the Fly deployment is `production`, so a local
  cluster can never write to the live `/ops` numbers.
- On kind the HPA shows `cpu: <unknown>` because the cluster has no metrics-server; install it
  (`kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml`
  with `--kubelet-insecure-tls`) to see it act. The HPA scales on CPU. LLM services usually scale on queue depth or p95 latency; that needs
  custom metrics (KEDA / Prometheus adapter). Not built.
- One namespace, no NetworkPolicy, no PodDisruptionBudget. Add them before any shared cluster.

## Proving it in CI

The `containers` job builds both images on every change to `backend/`, `frontend/`,
`llm_gateway/` or `deploy/`, and renders the manifests with `kubectl kustomize`. It never pushes
an image; the Fly deploy stays the only production path.

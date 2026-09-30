.PHONY: layout-eval demo-faiss ragas-eval mlflow-ui demo demo-llm demo-bedrock demo-ollama demo-graph demo-mcp demo-memory demo-budget resume context-study judge-eval test gate lint install install-all

install:            ## editable install with dev tools
	pip install -e '.[dev]'

install-all:        ## every optional extra (agents, llm, mcp, memory, ops, dev)
	pip install -e '.[all]'

demo:               ## run one autonomous research session
	python -m research_lab.run --iterations 5 --variants 6 --seed 3

demo-llm:           ## same session, but with Claude proposing (needs .[llm] + API key)
	python -m research_lab.run --iterations 5 --variants 6 --seed 3 --use-llm

demo-bedrock:       ## graph session with Claude on AWS Bedrock proposing (needs .[agents,llm] + AWS creds)
	LLM_PROVIDER=bedrock python -m research_lab.run_graph --use-llm --iterations 2 --variants 4 --seed 3

demo-ollama:        ## graph session with a local Ollama model proposing (needs .[agents] + ollama serve)
	LLM_PROVIDER=ollama python -m research_lab.run_graph --use-llm --iterations 2 --variants 4 --seed 3

demo-graph:         ## same session as a checkpointed LangGraph; pauses at the human gate (needs .[agents])
	python -m research_lab.run_graph --iterations 5 --variants 6 --seed 3

demo-mcp:           ## graph session with every backtest over MCP stdio (needs .[agents,mcp])
	python -m research_lab.run_graph --engine mcp --iterations 3 --variants 4 --seed 3

demo-budget:        ## LLM graph session capped at $0.02: stops early with 'stopped: budget' (needs .[agents,llm] + ANTHROPIC_API_KEY)
	LLM_PROVIDER=anthropic python -m research_lab.run_graph --use-llm --max-usd 0.02 --iterations 5 --variants 4 --seed 3 --no-gate

resume:             ## resume a paused graph run: make resume THREAD=<id> DECISION=approve|reject
	python -m research_lab.run_graph --resume $(THREAD) --decision $(DECISION)

context-study:      ## measure 3 context constructions (needs .[llm] + API key; costs cents)
	python -m research_lab.experiments.context_study --include-heuristic

judge-eval:         ## LLM judge vs 12 golden cases, exit 1 below 9/12 (needs .[llm] + a provider key; not in CI; < 1 cent)
	python -m eval.judge_eval

demo-faiss:         ## chatbot retriever on FAISS: build backend/.faiss, then one query (needs backend/requirements.txt)
	cd backend && VECTOR_BACKEND=faiss python ingest.py && VECTOR_BACKEND=faiss python retriever.py "what is a maximum drawdown?"

ragas-eval:         ## RAGAS-style metrics over 12 golden chatbot questions; --fake = offline judge (proves the harness only)
	python -m eval.ragas_eval --fake

layout-eval:        ## layout router: rules vs slm vs frontier, one table; --fake = scripted model rows (rules row is real)
	python -m eval.layout_eval --fake

mlflow-ui:          ## browse eval runs tracked with MLFLOW_TRACKING_URI=file:./.mlruns (needs .[dev]; MLflow 3 needs the opt-in for a file store)
	MLFLOW_ALLOW_FILE_STORE=true mlflow ui --backend-store-uri file:./.mlruns

test:               ## unit + smoke tests
	pytest

gate:               ## CI eval-gate: agent loop must still beat baseline
	python -m eval.run_gate

lint:               ## lint (needs .[dev])
	ruff check .

demo-memory:        ## two graph runs over one SQLite memory: run 2 samples from run 1's priors (needs .[agents])
	python -m research_lab.run_graph --memory sqlite --strategy nifty-expiry --iterations 3 --variants 5 --seed 3 --no-gate --thread mem-$$(date +%Y%m%dT%H%M%S)-a
	python -m research_lab.run_graph --memory sqlite --strategy nifty-expiry --iterations 3 --variants 5 --seed 3 --no-gate --thread mem-$$(date +%Y%m%dT%H%M%S)-b
	@if command -v sqlite3 >/dev/null 2>&1; then \
		sqlite3 .yantra/research.sqlite 'select run_id, count(*) from trials group by run_id;'; \
	else echo "  (install sqlite3 to inspect .yantra/research.sqlite)"; fi

# ---- containers & Kubernetes (ADR-0011; deploy/k8s/README.md) ----
.PHONY: docker-build docker-up k8s-up k8s-smoke k8s-status k8s-down
KIND_CLUSTER ?= yantra

docker-build:       ## build both app images locally (backend from the repo root, frontend from frontend/)
	docker build -t yantra-backend:local -f backend/Dockerfile .
	docker build -t yantra-frontend:local --build-arg NEXT_PUBLIC_BACKEND_URL=http://localhost:8000 frontend/

docker-up:          ## run backend (:8000) + frontend (:3000) with Compose; add `--profile private` for Ollama
	docker compose up --build

k8s-up:             ## local kind cluster + ingress-nginx + images + `kubectl apply -k deploy/k8s`
	kind get clusters | grep -qx $(KIND_CLUSTER) || kind create cluster --config deploy/kind/cluster.yaml
	kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/kind/deploy.yaml
	kubectl -n ingress-nginx rollout status deployment/ingress-nginx-controller --timeout=180s
	docker build -t yantra-backend:local -f backend/Dockerfile .
	docker build -t yantra-frontend:local --build-arg NEXT_PUBLIC_BACKEND_URL=http://yantra.local/api-backend frontend/
	kind load docker-image yantra-backend:local yantra-frontend:local --name $(KIND_CLUSTER)
	kubectl apply -k deploy/k8s

k8s-smoke:          ## wait for the rollout, then GET /health through the Ingress
	kubectl -n yantra rollout status deployment/backend --timeout=180s
	kubectl -n yantra rollout status deployment/frontend --timeout=180s
	curl -fsS -H 'Host: yantra.local' http://localhost/api-backend/health && echo
	curl -fsS -o /dev/null -w 'frontend %{http_code}\n' -H 'Host: yantra.local' http://localhost/

k8s-status:         ## pods, services, HPA in the yantra namespace
	kubectl -n yantra get deploy,pods,svc,hpa,ingress

k8s-down:           ## delete the local cluster
	kind delete cluster --name $(KIND_CLUSTER)

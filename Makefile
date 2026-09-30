.PHONY: demo demo-llm demo-bedrock demo-ollama demo-graph demo-mcp demo-memory resume context-study test gate lint install install-all

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

resume:             ## resume a paused graph run: make resume THREAD=<id> DECISION=approve|reject
	python -m research_lab.run_graph --resume $(THREAD) --decision $(DECISION)

context-study:      ## measure 3 context constructions (needs .[llm] + API key; costs cents)
	python -m research_lab.experiments.context_study --include-heuristic

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

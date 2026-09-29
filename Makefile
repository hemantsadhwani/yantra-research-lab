.PHONY: demo demo-llm demo-graph demo-mcp resume context-study test gate lint install install-all

install:            ## editable install with dev tools
	pip install -e '.[dev]'

install-all:        ## every optional extra (agents, llm, mcp, memory, ops, dev)
	pip install -e '.[all]'

demo:               ## run one autonomous research session
	python -m research_lab.run --iterations 5 --variants 6 --seed 3

demo-llm:           ## same session, but with Claude proposing (needs .[llm] + API key)
	python -m research_lab.run --iterations 5 --variants 6 --seed 3 --use-llm

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

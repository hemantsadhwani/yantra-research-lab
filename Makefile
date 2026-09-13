.PHONY: demo demo-llm context-study test gate lint install

install:            ## editable install with dev tools
	pip install -e '.[dev]'

demo:               ## run one autonomous research session
	python -m research_lab.run --iterations 5 --variants 6 --seed 3

demo-llm:           ## same session, but with Claude proposing (needs .[llm] + API key)
	python -m research_lab.run --iterations 5 --variants 6 --seed 3 --use-llm

context-study:      ## measure 3 context constructions (needs .[llm] + API key; costs cents)
	python -m research_lab.experiments.context_study --include-heuristic

test:               ## unit + smoke tests
	pytest

gate:               ## CI eval-gate: agent loop must still beat baseline
	python -m eval.run_gate

lint:               ## lint (needs .[dev])
	ruff check .

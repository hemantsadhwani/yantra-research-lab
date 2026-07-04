.PHONY: demo test gate lint install

install:            ## editable install with dev tools
	pip install -e '.[dev]'

demo:               ## run one autonomous research session
	python -m research_lab.run --iterations 5 --variants 6 --seed 3

test:               ## unit + smoke tests
	pytest

gate:               ## CI eval-gate: agent loop must still beat baseline
	python -m eval.run_gate

lint:               ## lint (needs .[dev])
	ruff check .

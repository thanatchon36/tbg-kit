PY ?= .venv/bin/python
WS ?= work

.PHONY: setup demo synth init status build analyze figures explorer paper all smoke docs test clean

setup:          ## create venv and install the package (needs uv)
	uv venv .venv --python 3.12
	uv pip install --python .venv/bin/python -e ".[dev]"

demo:           ## synthetic end-to-end run -> demo/figures, demo/explorer, demo/paper/paper.pdf
	$(PY) -m tbg demo

synth:          ## (re)generate synthetic raw data in demo/. NEVER a substitute for real data
	$(PY) -m tbg synth

init:           ## create the workspace $(WS)/ with blank input files
	$(PY) -m tbg --workspace $(WS) init

status:         ## coverage report and review queues
	$(PY) -m tbg --workspace $(WS) status

build:          ## raw -> processed tables (entity resolution, holdings, links)
	$(PY) -m tbg --workspace $(WS) build

analyze:        ## ultimate ownership, groups, pyramids, finance-business nexus
	$(PY) -m tbg --workspace $(WS) analyze

figures:        ## poster network maps, group trees, paper figures (with overlap QA)
	$(PY) -m tbg --workspace $(WS) figures

explorer:       ## self-contained interactive explorer -> $(WS)/explorer/index.html
	$(PY) -m tbg --workspace $(WS) explorer

paper:          ## LaTeX tables and macros, compile $(WS)/paper/paper.pdf + arXiv bundle
	$(PY) -m tbg --workspace $(WS) paper

all: build analyze figures explorer paper

smoke:          ## synthetic build + analyze in ci-demo/ (what CI runs)
	$(PY) -m tbg --workspace ci-demo synth
	$(PY) -m tbg --workspace ci-demo build
	$(PY) -m tbg --workspace ci-demo analyze

docs: demo      ## refresh the synthetic showcase in docs/ from demo/
	cp demo/explorer/index.html docs/explorer.html
	cp demo/paper/paper.pdf docs/paper_demo.pdf

test:
	$(PY) -m pytest -q

clean:
	rm -rf demo ci-demo .pytest_cache

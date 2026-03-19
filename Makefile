PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,$(shell if command -v python3.12 >/dev/null 2>&1; then echo python3.12; else echo python3; fi))
PIP ?= $(PYTHON) -m pip
PYTEST ?= $(PYTHON) -m pytest
RUFF ?= $(PYTHON) -m ruff
MYPY ?= $(PYTHON) -m mypy
SPHINX ?= $(PYTHON) -m sphinx
BUILD ?= $(PYTHON) -m build
TWINE ?= $(PYTHON) -m twine
CHALLENGE_BIN ?= $(CURDIR)/.challenge-tools/bin
CHALLENGE_PATH = PATH="$(CHALLENGE_BIN):$(CURDIR)/.venv/bin:$$PATH"

.PHONY: help check-python dev install-dev generate-example-docs \
	generate-case-study-docs generate-challenge-docs case-study-docs-check \
	challenge-docs-check challenge-deps challenge lint fmt fmt-check type test qa coverage \
	docstrings-check run-example run-examples run-case-study run-case-studies \
	challenges-subset challenges-full challenges-metrics docs docs-build \
	docs-check docs-linkcheck release-check ci clean

help:
	@echo "Common targets:"
	@echo "  dev              Install the project in editable mode with dev dependencies."
	@echo "  test             Run the pytest suite."
	@echo "  qa               Run lint, fmt-check, type, and test."
	@echo "  run-examples     Execute the runnable example scripts."
	@echo "  run-case-studies Execute the optional case-study scripts."
	@echo "  challenge-deps   Install optional live challenge runtimes into .challenge-tools/."
	@echo "  challenge        Run one live challenge case (set CASE=<id>)."
	@echo "  challenges-subset Run the reduced live raw-upstream challenge suite."
	@echo "  challenges-full  Run the broader local live raw-upstream challenge suite."
	@echo "  docs             Build the HTML docs."
	@echo "  ci               Run the main local CI checks."

check-python:
	@$(PYTHON) -c "import pathlib, sys; print(f'Using Python {sys.version.split()[0]} at {pathlib.Path(sys.executable)}'); raise SystemExit(0 if sys.version_info >= (3, 12) else 1)" || (echo "Python >= 3.12 is required by pyproject.toml"; exit 1)

dev:
	$(PIP) install --upgrade pip setuptools wheel
	$(PIP) install -e ".[dev]"

install-dev: dev

lint: check-python
	$(RUFF) check .

fmt: check-python
	$(RUFF) format .

fmt-check: check-python
	$(RUFF) format --check .

type: check-python
	$(MYPY) src

test: check-python
	PYTHONPATH=src $(PYTEST) -q

qa: lint fmt-check type test

coverage: check-python
	mkdir -p artifacts/coverage
	PYTHONPATH=src $(PYTEST) --cov=src/mcpme --cov-report=term --cov-report=json:artifacts/coverage/coverage.json -q
	$(PYTHON) scripts/check_coverage_thresholds.py --coverage-json artifacts/coverage/coverage.json

docstrings-check: check-python
	$(PYTHON) scripts/check_docstrings.py

generate-example-docs: check-python
	$(PYTHON) scripts/generate_example_docs.py

generate-case-study-docs: check-python
	$(PYTHON) scripts/generate_case_study_docs.py

generate-challenge-docs: check-python
	$(PYTHON) scripts/generate_challenge_docs.py

case-study-docs-check: check-python
	$(PYTHON) scripts/generate_case_study_docs.py --check

challenge-docs-check: check-python
	$(PYTHON) scripts/generate_challenge_docs.py --check

run-example: run-examples

run-examples: check-python
	PYTHONPATH=src $(PYTHON) examples/basic_usage.py
	PYTHONPATH=src $(PYTHON) examples/argparse_cli_wrapper.py
	PYTHONPATH=src $(PYTHON) examples/command_scaffold.py
	PYTHONPATH=src $(PYTHON) examples/openapi_scaffold.py
	PYTHONPATH=src $(PYTHON) examples/package_scaffold.py
	PYTHONPATH=src $(PYTHON) examples/subprocess_wrapper.py
	PYTHONPATH=src $(PYTHON) examples/runtime_server.py

run-case-study: check-python
	@if [ -z "$(CASE)" ]; then echo "Set CASE=<case_study_id>."; exit 1; fi
	$(CHALLENGE_PATH) PYTHONPATH=src $(PYTHON) case_studies/$(CASE)/ingest.py
	$(CHALLENGE_PATH) PYTHONPATH=src $(PYTHON) case_studies/$(CASE)/use.py

run-case-studies: check-python
	$(CHALLENGE_PATH) PYTHONPATH=src $(PYTHON) case_studies/su2_cli/ingest.py
	$(CHALLENGE_PATH) PYTHONPATH=src $(PYTHON) case_studies/su2_cli/use.py
	$(CHALLENGE_PATH) PYTHONPATH=src $(PYTHON) case_studies/pycycle_mpcycle/ingest.py
	$(CHALLENGE_PATH) PYTHONPATH=src $(PYTHON) case_studies/pycycle_mpcycle/use.py
	$(CHALLENGE_PATH) PYTHONPATH=src $(PYTHON) case_studies/tigl_cpacs/ingest.py
	$(CHALLENGE_PATH) PYTHONPATH=src $(PYTHON) case_studies/tigl_cpacs/use.py

challenge-deps: check-python
	$(PYTHON) scripts/install_challenge_deps.py --profile $(or $(PROFILE),full)

challenge: check-python
	@if [ -z "$(CASE)" ]; then echo "Set CASE=<challenge_id>."; exit 1; fi
	mkdir -p artifacts/challenges/single
	$(CHALLENGE_PATH) PYTHONPATH=src $(PYTHON) scripts/run_challenges.py \
		--catalog-dir challenges/cases \
		--tier all \
		--only "$(CASE)" \
		--artifact-root artifacts/challenges/single \
		--metrics-json artifacts/challenges/single/challenges_metrics.json \
		--junit-xml artifacts/challenges/single/challenges.junit.xml \
		--summary-md artifacts/challenges/single/summary.md

challenges-subset: check-python
	mkdir -p artifacts/challenges/gha_subset
	$(CHALLENGE_PATH) PYTHONPATH=src $(PYTHON) scripts/run_challenges.py \
		--tier gha_subset \
		--artifact-root artifacts/challenges/gha_subset \
		--metrics-json artifacts/challenges/gha_subset/challenges_metrics.json \
		--junit-xml artifacts/challenges/gha_subset/challenges.junit.xml \
		--summary-md artifacts/challenges/gha_subset/summary.md

challenges-full: check-python
	mkdir -p artifacts/challenges/full
	$(CHALLENGE_PATH) PYTHONPATH=src $(PYTHON) scripts/run_challenges.py \
		--tier all \
		--artifact-root artifacts/challenges/full \
		--metrics-json artifacts/challenges/full/challenges_metrics.json \
		--junit-xml artifacts/challenges/full/challenges.junit.xml \
		--summary-md artifacts/challenges/full/summary.md

challenges-metrics: check-python
	PYTHONPATH=src $(PYTHON) scripts/generate_challenges_badge.py

docs-build: generate-example-docs generate-case-study-docs
	PYTHONPATH=src $(SPHINX) -b html docs docs/_build/html -n -W --keep-going -E

docs-check: check-python
	$(PYTHON) scripts/generate_example_docs.py --check
	$(PYTHON) scripts/generate_case_study_docs.py --check
	$(PYTHON) scripts/check_docs_consistency.py

docs-linkcheck: check-python
	PYTHONPATH=src $(SPHINX) -b linkcheck docs docs/_build/linkcheck -W --keep-going -E

docs: docs-build

release-check: check-python
	rm -rf build dist
	$(BUILD)
	$(TWINE) check dist/*

ci: qa coverage docstrings-check docs-check challenge-docs-check run-example release-check

clean:
	rm -rf .coverage .mypy_cache .pytest_cache .ruff_cache artifacts build dist docs/_build
	find src -maxdepth 2 -type d -name "*.egg-info" -prune -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "__pycache__" -prune -exec rm -rf {} + 2>/dev/null || true
	find . -type f \( -name "*.pyc" -o -name ".coverage.*" \) -exec rm -f {} + 2>/dev/null || true

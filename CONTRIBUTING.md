# Contributing

## Development Setup

```bash
python -m venv .venv
source .venv/bin/activate
make dev
```

## Local Quality Checks

Run these before opening a pull request:

```bash
make fmt
make lint
make type
make docstrings-check
make test
make run-examples
make docs-check
make docs
```

Optional but useful:

```bash
python scripts/generate_challenge_docs.py
make challenge-docs-check
make challenge CASE=openmdao_file_utils
make challenges-subset
make challenges-full
pre-commit install
pre-commit run --all-files
```

## Pull Request Guidelines

- Keep changes small enough to review quickly.
- Add or update tests for behavior changes.
- Update docs and examples when interfaces change.
- Update `challenges/` fixtures, catalog entries, and reports when the live
  raw-upstream suite changes.
- Regenerate checked-in challenge READMEs when challenge catalog files change.
- Regenerate checked-in example docs when example docstrings change.
- Keep the top-level `mcpme` public API small and deliberate.
- Describe what changed and how you validated it.

## Code Style

- Python 3.12+ target
- Ruff for linting and formatting
- Mypy for type checking
- Pytest for tests
- Sphinx-style field-list docstrings in `src/`, `examples/`, and `scripts/`

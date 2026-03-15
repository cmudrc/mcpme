# AGENTS.md

## Purpose

This repository builds `mcpme`, a deterministic Python 3.12+ library for
wrapping engineering tools as MCP servers. Keep changes focused, keep the
public API intentional, and prefer standard-library solutions unless a
third-party dependency clearly improves the maintenance story.

## Setup

- Create and activate a virtual environment:
  - `python -m venv .venv`
  - `source .venv/bin/activate`
- The preferred interpreter target lives in `.python-version` (`3.12.12`).
- Install local tooling with `make dev`.

## Testing And Validation

Use the smallest useful check while iterating, then run the full gate before
merging.

- Fast local loop:
  - `make fmt`
  - `make lint`
  - `make type`
  - `make test`
- If docs changed:
  - `make docs-check`
  - `make docs`
- If the example changed:
  - `make run-examples`
  - `python scripts/generate_example_docs.py`
- Pre-merge baseline:
  - `make ci`
- Pre-publish baseline:
  - `make release-check`

## Public Vs Private Boundaries

- The supported public surface is whatever is re-exported from
  `src/mcpme/__init__.py`.
- Keep that top-level surface minimal. Prefer stable entry points and a small
  set of user-facing types over re-exporting every internal model.
- Prefer adding new public behavior to stable top-level modules before creating
  deeper internal package trees.
- If you add internal helper modules later, prefix them with `_` and keep them
  out of the top-level exports unless there is a deliberate API decision.

## Behavioral Guardrails

- Keep tests deterministic and offline by default.
- Update tests, docs, and examples alongside behavior changes.
- Keep example module docstrings authoritative. Generated example docs should be
  refreshed whenever examples change.
- Avoid broad dependency growth in the base install.
- Keep stage 1 fully non-AI. Do not add LLM-based discovery or generation to
  the baseline path.
- Preserve inspectable artifacts and avoid hiding what the wrapped tool
  actually ran.
- Prefer wrapping and explicit manifests over rewriting validated tools.

## Keep This File Up To Date

Update this file whenever the contributor workflow changes, especially when
setup commands, validation commands, or the public API expectations change.

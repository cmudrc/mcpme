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
  - `make case-study-docs-check`
  - `make docs-check`
  - `make docs`
- If case studies changed:
  - `python scripts/generate_case_study_docs.py`
  - `make run-case-studies`
- If the example changed:
  - `make run-examples`
  - `python scripts/generate_example_docs.py`
- If the live challenge track changed:
  - `python scripts/generate_challenge_docs.py`
  - `make challenge-docs-check`
  - `make challenge CASE=openmdao_file_utils`
  - `make challenges-subset`
  - `make challenges-metrics`
- If you are working on broader raw-upstream ingestion:
  - `make challenges-full`
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
- The live raw-upstream challenge suite is the explicit exception. It is
  intentionally live, separate from the main gate, and should remain
  non-gating.
- Update tests, docs, and examples alongside behavior changes.
- Keep `case_studies/` separate from the small core `examples/` contract. Case
  studies may depend on heavyweight optional upstream runtimes and may report
  `skipped_unavailable`, but they should still use only the public `mcpme`
  surface.
- Keep each case-study directory readable as a real ingest/persist/use flow:
  `case_studies/<id>/ingest.py` should write the deterministic artifact pair
  `generated_facade.py` and `scaffold_report.json` under
  `artifacts/case_studies/<id>/`, `case_studies/<id>/serve.py` should expose
  that saved generated facade over stdio MCP, and `case_studies/<id>/use.py`
  should demonstrate the saved capabilities through MCP requests.
- Keep checked-in support inputs under `examples/support/<id>/` and
  `case_studies/support/<id>/`. Generated facades and retained execution
  artifacts belong under `artifacts/` and should not be promoted into the
  support trees.
- Keep case-study `use.py` module docstrings authoritative. Generated
  case-study docs should be refreshed whenever those walkthroughs change.
- Keep example module docstrings authoritative. Generated example docs should be
  refreshed whenever examples change.
- Keep `challenges/` out of the public API and example-doc contract unless
  there is an explicit product decision to promote something out of it.
- Keep each checked-in challenge self-contained: the case directory should be
  readable on its own, with its canonical `challenge.toml`, local fixtures when
  needed, and an up-to-date generated `README.md`.
- Avoid broad dependency growth in the base install.
- Keep stage 1 fully non-AI. Do not add LLM-based discovery or generation to
  the baseline path.
- Preserve inspectable artifacts and avoid hiding what the wrapped tool
  actually ran.
- Prefer wrapping and explicit manifests over rewriting validated tools.

## Keep This File Up To Date

Update this file whenever the contributor workflow changes, especially when
setup commands, validation commands, or the public API expectations change.

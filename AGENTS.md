# AGENTS.md

## Purpose

This repository builds `mcpcraft`, a deterministic Python 3.12+ library for
wrapping engineering tools as MCP servers. Keep changes focused, keep the
public API intentional, and prefer standard-library solutions unless a
third-party dependency clearly improves the maintenance story.

## Setup

- Create and activate a virtual environment:
  - `python -m venv .venv`
  - `source .venv/bin/activate`
- The preferred interpreter target lives in `.python-version` (`3.12.12`).
- Install local tooling with `make dev`.
- Install the optional live challenge runtimes with `make challenge-deps`
  before running the broader raw-upstream lanes.

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
- If a core example changed:
  - `make run-examples`
  - `python scripts/generate_example_docs.py`
- If a real-world example changed:
  - `make run-real-world-examples`
  - `python scripts/generate_example_docs.py`
- If the live challenge track changed:
  - `make challenge-deps`
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
  `src/mcpcraft/__init__.py`.
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
- Keep `examples/core/` separate from the richer optional
  `examples/real_world/` lane. Real-world examples may depend on heavyweight
  optional upstream runtimes and may report `skipped_unavailable`, but they
  should still use only the public `mcpcraft` surface.
- Keep each real-world example directory readable as a real ingest/persist/use
  flow: `examples/real_world/<id>/ingest.py` should write the deterministic
  artifact pair `generated_facade.py` and `scaffold_report.json` under
  `artifacts/examples/real_world/<id>/`, `examples/real_world/<id>/serve.py`
  should expose that saved generated facade over stdio MCP, and
  `examples/real_world/<id>/use.py` should demonstrate the saved capabilities
  through MCP requests.
- Keep checked-in support inputs under `examples/support/<id>/` for core
  examples and `examples/support/real_world/<id>/` for real-world examples.
  Generated facades and retained execution artifacts belong under
  `artifacts/` and should not be promoted into the support trees.
- Keep real-world example `use.py` module docstrings authoritative. Generated
  example docs should be refreshed whenever those walkthroughs change.
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

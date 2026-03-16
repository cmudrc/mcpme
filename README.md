# mcpme

[![Challenges Live](https://raw.githubusercontent.com/cmudrc/mcpme/main/.github/badges/challenges-live-subset.svg)](https://github.com/cmudrc/mcpme/actions/workflows/challenges.yml)

`mcpme` is a deterministic Python library for exposing engineering tools as MCP
servers.

The stage-1 baseline is intentionally non-AI:

- No LLMs are used for discovery, schema generation, translation, or execution.
- Wrappers preserve trusted tools instead of trying to replace them.
- Inputs, outputs, and execution artifacts stay inspectable.

## What It Does

`mcpme` currently supports:

- Source-first Python discovery for modules, packages, files, and directories
- Explicit callable registration when you want runtime reflection by choice
- Explicitly registered `argparse` command wrappers
- Deterministic one-shot scaffolding for installed packages and modules
- Deterministic one-shot scaffolding for standalone CLI tools
- Deterministic one-shot scaffolding for OpenAPI JSON or YAML specs
- Manifest-driven subprocess tools loaded from `pyproject.toml` or `mcpme.toml`
- Deterministic hydration/dehydration for subprocess-based tools
- Path- and binary-aware schemas, including `Path`, `bytes`, and `Annotated`
- Explicit retained-output rules for file and directory artifacts
- Artifact capture plus MCP `_meta` execution records for reproducibility and trust
- Background subprocess jobs with persisted records, log tailing, and cancellation
- A small stdio MCP runtime plus `inspect`, `manifest`, and `serve` CLI flows

The top-level public API is intentionally small. Stable imports live at the
package root, while lower-level config and manifest model details stay in
submodules until they prove they should be part of the long-term contract.

The runnable examples are treated as part of that contract. They use only the
top-level public API, their module docstrings generate checked-in Sphinx pages,
and automated tests verify that examples and docs stay aligned.

Separately, the repository keeps a live raw-upstream challenge track under
`challenges/`. That suite is intentionally non-gating and separate from the
public docs/examples contract, but it is where we pressure-test one-shot
ingestion against real upstream engineering packages and CLI tools.

## Quickstart

Requires Python 3.12+.

```bash
python -m venv .venv
source .venv/bin/activate
make dev
make test
make run-examples
```

Generate a manifest from the bundled example:

```bash
PYTHONPATH=src python examples/basic_usage.py
PYTHONPATH=src python examples/argparse_cli_wrapper.py
PYTHONPATH=src python examples/command_scaffold.py
PYTHONPATH=src python examples/openapi_scaffold.py
PYTHONPATH=src python examples/package_scaffold.py
PYTHONPATH=src python examples/subprocess_wrapper.py
PYTHONPATH=src python examples/runtime_server.py
```

Use the CLI against a target module or file:

```bash
mcpme inspect examples/basic_usage.py
mcpme manifest examples/basic_usage.py
```

Generate a deterministic facade first when the source surface is a package,
standalone CLI, or OpenAPI spec:

```bash
mcpme scaffold-package some_package artifacts/generated_package.py
mcpme scaffold-command artifacts/generated_cli.py -- tool
mcpme scaffold-openapi api.json artifacts/generated_api.py
```

For Python files and source-backed modules, discovery is source-first by
default. `mcpme` parses signatures, annotations, and docstrings without
importing user code, then lazily loads the callable only when execution
happens. If you need import-based discovery for a special case, set
`python_discovery_mode = "import"` in config.

The one-shot scaffolding flows are deliberately inspectable, but they do have
different trust boundaries:

- `scaffold-package` imports the target package or selected submodules so it can
  inspect live functions and classes, then writes a reviewable facade module.
- `scaffold-command` executes the target command with `--help` and only emits
  named parameters when that help contract is clear enough to parse
  deterministically.
- `scaffold-openapi` reads the local OpenAPI document and generates plain Python
  HTTP wrappers that you can review or edit before serving.

## Configuration

`mcpme` reads embedded config from `pyproject.toml` under `[tool.mcpme]` and
also supports a standalone `mcpme.toml`.

Example:

```toml
[tool.mcpme]
artifact_mode = "summary"
artifact_root = ".mcpme-artifacts"
python_discovery_mode = "source"

[[tool.mcpme.subprocess]]
name = "emit_artifacts"
description = "Render an input file, emit a binary result, and retain reports."
argv = ["python", "emit_artifacts.py", "input.json"]
result_kind = "file_bytes"
result_path = "report.bin"

[tool.mcpme.subprocess.input_schema]
type = "object"
required = ["message"]

[tool.mcpme.subprocess.input_schema.properties.message]
type = "string"

[[tool.mcpme.subprocess.files]]
path = "input.json"
template = "{{\"message\": \"{message}\"}}"

[[tool.mcpme.subprocess.outputs]]
path = "reports"
kind = "directory"
when = "success"
```

Useful config notes:

- `artifact_mode = "summary"` keeps invocation records, execution records, logs,
  structured results, and explicitly retained outputs without keeping the whole
  workspace.
- `artifact_mode = "full"` keeps the full workspace in addition to those
  records.
- `python_discovery_mode = "source"` is the default and avoids importing Python
  targets during discovery.
- `python_discovery_mode = "import"` is an explicit escape hatch for cases that
  cannot be described statically.

## Filesystem Semantics

`mcpme` understands a few useful Python-side filesystem conventions:

- `Path` maps to a string schema with `format: "path"`.
- `Annotated[Path, "file"]` and `Annotated[Path, "directory"]` make path
  intent explicit without needing an AI layer.
- `bytes` maps to base64-encoded strings for deterministic transport.

That makes it practical to wrap callables like:

```python
from pathlib import Path
from typing import Annotated

def solve(
    deck: Annotated[Path, "file"],
    workdir: Annotated[Path, "directory"],
) -> Path:
    ...
```

## Runtime Extensions

Every executed tool result now includes deterministic `_meta` fields with local
artifact and execution details, including the retained artifact directory and a
machine-readable artifact listing.

For long-running subprocess tools, clients can opt into background execution by
adding:

```json
{
  "_meta": {
    "mcpme/runMode": "async"
  }
}
```

to `tools/call` params. The runtime then exposes these deterministic extension
methods:

- `mcpme/jobs/list`
- `mcpme/jobs/get`
- `mcpme/jobs/tail`
- `mcpme/jobs/cancel`

## Deterministic Roadmap

The repository spec lives in `docs/specification.rst` and currently divides the
roadmap into:

- Stage 1: deterministic baseline
- Stage 2: optional post-generation cleanup after deterministic outputs exist

Stage 1 is the active implementation target and remains explicitly non-AI.

## Development

Useful local commands:

```bash
make fmt
make lint
make type
make test
make run-examples
make challenges-subset
make challenges-full
make docs-check
make docs
make ci
```

The live challenge suite lives in `challenges/README.md`. `make challenges-subset`
runs the reduced GitHub-hosted subset, while `make challenges-full` runs the
broader local-only suite. `make challenges-metrics` regenerates the reduced
subset badge from `artifacts/challenges/gha_subset/challenges_metrics.json`.

## Docs

Build the docs locally with:

```bash
make docs
```

The generated HTML output is written to `docs/_build/html/`.

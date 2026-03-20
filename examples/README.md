# Examples

The examples in `mcpcraft` stay intentionally small, deterministic, and public-API
only.

## Core

- imports from the top-level `mcpcraft` package rather than internal modules,
- includes a canonical module docstring that is used to generate Sphinx docs,
- exercises at least one real deterministic wrapping pattern, and
- is runnable from the repository root with `PYTHONPATH=src`.

Core examples that need local helper inputs keep them checked in under
`examples/support/<example_id>/`, so the environment is inspectable before
execution. Derived outputs such as generated facades and retained run artifacts
belong under `artifacts/examples/core/<example_id>/`.

Included core examples:

- `basic_usage.py`: wrap a typed Python callable and inspect the generated manifest.
- `argparse_cli_wrapper.py`: wrap an existing `argparse` CLI using `ArgparseCommand`.
- `command_scaffold.py`: ingest a standalone CLI through `mcpcraft scaffold-command`.
- `openapi_scaffold.py`: ingest an OpenAPI document through `mcpcraft scaffold-openapi`.
- `package_scaffold.py`: ingest a package with functions and classes through `mcpcraft scaffold-package`.
- `subprocess_wrapper.py`: wrap a file-driven legacy-style batch tool from TOML config.
- `runtime_server.py`: send JSON-RPC requests through `McpServer` and optionally serve stdio.

Run the core lane with:

```bash
PYTHONPATH=src python examples/core/basic_usage.py
PYTHONPATH=src python examples/core/argparse_cli_wrapper.py
PYTHONPATH=src python examples/core/command_scaffold.py
PYTHONPATH=src python examples/core/openapi_scaffold.py
PYTHONPATH=src python examples/core/package_scaffold.py
PYTHONPATH=src python examples/core/subprocess_wrapper.py
PYTHONPATH=src python examples/core/runtime_server.py
```

## Real World

The richer optional lane lives under `examples/real_world/`. Those examples
keep their checked-in support assets under `examples/support/real_world/`,
write derived outputs under `artifacts/examples/real_world/`, and use an
explicit `ingest.py -> serve.py -> use.py` flow so the generated facade
remains inspectable.

See [examples/real_world/README.md](real_world/README.md) for the current
inventory and run commands.

# Examples

The examples in `mcpwrap` stay intentionally small, deterministic, and public-API
only.

Each Python example:

- imports from the top-level `mcpwrap` package rather than internal modules,
- includes a canonical module docstring that is used to generate Sphinx docs,
- exercises at least one real deterministic wrapping pattern, and
- is runnable from the repository root with `PYTHONPATH=src`.

Examples that need local helper inputs keep them checked in under
`examples/support/<example_id>/`, so the environment is inspectable before
execution. Derived outputs such as generated facades and retained run artifacts
belong under `artifacts/examples/<example_id>/`.

Included examples:

- `basic_usage.py`: wrap a typed Python callable and inspect the generated manifest.
- `argparse_cli_wrapper.py`: wrap an existing `argparse` CLI using `ArgparseCommand`.
- `command_scaffold.py`: ingest a standalone CLI through `mcpwrap scaffold-command`.
- `openapi_scaffold.py`: ingest an OpenAPI document through `mcpwrap scaffold-openapi`.
- `package_scaffold.py`: ingest a package with functions and classes through `mcpwrap scaffold-package`.
- `subprocess_wrapper.py`: wrap a file-driven legacy-style batch tool from TOML config.
- `runtime_server.py`: send JSON-RPC requests through `McpServer` and optionally serve stdio.

Run it locally with:

```bash
PYTHONPATH=src python examples/basic_usage.py
PYTHONPATH=src python examples/argparse_cli_wrapper.py
PYTHONPATH=src python examples/command_scaffold.py
PYTHONPATH=src python examples/openapi_scaffold.py
PYTHONPATH=src python examples/package_scaffold.py
PYTHONPATH=src python examples/subprocess_wrapper.py
PYTHONPATH=src python examples/runtime_server.py
```

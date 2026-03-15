# Examples

The examples in `mcpme` stay intentionally small, deterministic, and public-API
only.

Each Python example:

- imports from the top-level `mcpme` package rather than internal modules,
- includes a canonical module docstring that is used to generate Sphinx docs,
- exercises at least one real deterministic wrapping pattern, and
- is runnable from the repository root with `PYTHONPATH=src`.

Included examples:

- `basic_usage.py`: wrap a typed Python callable and inspect the generated manifest.
- `argparse_cli_wrapper.py`: wrap an existing `argparse` CLI using `ArgparseCommand`.
- `subprocess_wrapper.py`: wrap a file-driven legacy-style batch tool from TOML config.
- `runtime_server.py`: send JSON-RPC requests through `McpServer` and optionally serve stdio.

Run it locally with:

```bash
PYTHONPATH=src python examples/basic_usage.py
PYTHONPATH=src python examples/argparse_cli_wrapper.py
PYTHONPATH=src python examples/subprocess_wrapper.py
PYTHONPATH=src python examples/runtime_server.py
```

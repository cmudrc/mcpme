# mcpcraft

[![Challenges Live](https://raw.githubusercontent.com/cmudrc/mcpcraft/main/.github/badges/challenges-live-subset.svg)](https://github.com/cmudrc/mcpcraft/actions/workflows/challenges.yml)

`mcpcraft` is a deterministic Python library for wrapping engineering tools as MCP
servers.

The motivation is simple: engineers should be able to expose trusted tools
without replacing them with opaque AI behavior. `mcpcraft` starts from public
interfaces, docstrings, CLI help, and explicit file contracts. The first pass
is intentionally non-AI, wrapper-first, and inspectable.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
make dev
```

## Killer Usage Examples

Turn a normal Python module into an MCP manifest without importing user code
during discovery:

```bash
mcpcraft manifest examples/core/basic_usage.py
```

One-shot wrap an installed engineering package into a plain Python facade you
can review:

```bash
mcpcraft scaffold-package openmdao.utils.file_utils artifacts/openmdao_file_utils.py
mcpcraft manifest artifacts/openmdao_file_utils.py
```

One-shot wrap a real CLI tool:

```bash
mcpcraft scaffold-command artifacts/gmsh_wrapper.py -- gmsh -help
mcpcraft inspect artifacts/gmsh_wrapper.py
```

Serve a wrapped target over stdio MCP:

```bash
mcpcraft serve examples/core/basic_usage.py
```

Run the maintained runnable examples:

```bash
make run-examples
```

The smaller core examples live under `examples/core/`, keep inspectable source
inputs under `examples/support/`, and write only derived outputs under
`artifacts/examples/core/`.

Run the richer real-world examples for real upstream surfaces:

```bash
make run-real-world-examples
make run-real-world-example CASE=pycycle_mpcycle
```

Each real-world example directory under `examples/real_world/` follows a more
realistic `ingest.py` then `serve.py` then `use.py` flow, with support inputs
under `examples/support/real_world/` and derived outputs under
`artifacts/examples/real_world/`. The handoff is standardized around
`generated_facade.py` plus `scaffold_report.json` rather than a bespoke state
blob.

Run the live raw-upstream challenge cases:

```bash
make challenges-subset
make challenge CASE=openmdao_file_utils
```

The broader live challenge track lives in [challenges/README.md](challenges/README.md).
The richer optional example lane lives in [examples/real_world/README.md](examples/real_world/README.md).

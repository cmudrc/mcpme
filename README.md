# mcpme

[![Challenges Live](https://raw.githubusercontent.com/cmudrc/mcpme/main/.github/badges/challenges-live-subset.svg)](https://github.com/cmudrc/mcpme/actions/workflows/challenges.yml)

`mcpme` is a deterministic Python library for wrapping engineering tools as MCP
servers.

The motivation is simple: engineers should be able to expose trusted tools
without replacing them with opaque AI behavior. `mcpme` starts from public
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
mcpme manifest examples/basic_usage.py
```

One-shot wrap an installed engineering package into a plain Python facade you
can review:

```bash
mcpme scaffold-package openmdao.utils.file_utils artifacts/openmdao_file_utils.py
mcpme manifest artifacts/openmdao_file_utils.py
```

One-shot wrap a real CLI tool:

```bash
mcpme scaffold-command artifacts/gmsh_wrapper.py -- gmsh -help
mcpme inspect artifacts/gmsh_wrapper.py
```

Serve a wrapped target over stdio MCP:

```bash
mcpme serve examples/basic_usage.py
```

Run the maintained runnable examples:

```bash
make run-examples
```

The smaller runnable examples keep inspectable source inputs under
`examples/support/` and write only derived outputs under `artifacts/examples/`.

Run the richer case studies for real upstream surfaces:

```bash
make run-case-studies
make run-case-study CASE=pycycle_mpcycle
```

Each case-study directory now follows a more realistic `ingest.py` then
`serve.py` then `use.py` flow, with support inputs under
`case_studies/support/` and derived outputs under `artifacts/case_studies/`.

Run the live raw-upstream challenge cases:

```bash
make challenges-subset
make challenge CASE=openmdao_file_utils
```

The broader live challenge track lives in [challenges/README.md](challenges/README.md).
The separate case-study lane lives in [case_studies/README.md](case_studies/README.md).

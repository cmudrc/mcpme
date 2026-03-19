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

Install the optional live-challenge runtimes into the repo-local
`.challenge-tools/` prefix when you want the broader raw-upstream lane:

```bash
make challenge-deps
```

## Usage Examples

For wrapped targets that need a generated facade, the CLI flow stays explicit:
scaffold first, inspect the manifest second, and serve that saved facade last.

Scaffold an installed package, inspect the generated manifest, then serve it:

```bash
mcpme scaffold-package openmdao.utils.file_utils generated_facade.py
mcpme manifest generated_facade.py
mcpme serve generated_facade.py
```

Scaffold a real CLI command through its help surface, inspect the manifest,
then serve it:

```bash
mcpme scaffold-command generated_facade.py -- gmsh -help
mcpme manifest generated_facade.py
mcpme serve generated_facade.py
```

Scaffold an OpenAPI document into a plain Python HTTP facade, inspect the
manifest, then serve it:

```bash
mcpme scaffold-openapi api.json generated_facade.py
mcpme manifest generated_facade.py
mcpme serve generated_facade.py
```

Source-backed Python files already are the inspectable surface, so they skip
the scaffold step:

```bash
mcpme manifest tool_module.py
mcpme serve tool_module.py
```

## Real-Upstream Coverage

### Case Studies

The case studies are the primary inspectable integration lane for real
engineering surfaces. Each case follows the same persisted handoff:
`ingest.py` scaffolds and writes `generated_facade.py` plus
`scaffold_report.json`, `serve.py` exposes that saved facade over stdio MCP,
and `use.py` exercises the same saved tools through MCP requests.

| Case Study | Upstream Surface | What It Covers | Run |
| --- | --- | --- | --- |
| `su2_cli` | `SU2_CFD` CLI | Command scaffolding around a heavyweight CFD executable. | `make run-case-study CASE=su2_cli` |
| `pycycle_mpcycle` | `pycycle.api.MPCycle` | Package scaffolding plus a session-oriented runtime lifecycle. | `make run-case-study CASE=pycycle_mpcycle` |
| `tigl_cpacs` | TiGL/TiXI helper package + CPACS fixture | Package scaffolding against native bindings and checked-in engineering data. | `make run-case-study CASE=tigl_cpacs` |

Run the full lane or step through one case manually:

```bash
make run-case-studies
PYTHONPATH=src python case_studies/pycycle_mpcycle/ingest.py
PYTHONPATH=src python case_studies/pycycle_mpcycle/serve.py
PYTHONPATH=src python case_studies/pycycle_mpcycle/use.py
```

### Challenges

The challenge lane is the live, non-gating raw-upstream stress test. Each case
is self-contained under `challenges/cases/<id>/` with a canonical
`challenge.toml`, any tiny checked-in fixtures it needs, and a generated
README. Unlike the case studies, ingestion and workflow stay compressed into
the challenge spec so the wrapping problem remains explicit.

| Challenge | Tier | Target | What It Probes |
| --- | --- | --- | --- |
| `aerosandbox_root` | `local_full` | `aerosandbox` | Package-root ingestion around `Atmosphere` methods. |
| `build123d_importers` | `gha_subset` | `build123d.importers` | Filtered package ingestion across STL and SVG importer routes. |
| `build123d_root` | `local_full` | `build123d` | Broader package-root wrapping narrowed to importer workflows. |
| `gmsh_cli` | `gha_subset` | `gmsh` | CLI wrapping that produces a real mesh file from a tiny `.geo` input. |
| `gmsh_module_root` | `local_full` | `gmsh` | Python module-root lifecycle coverage for initialize/check/clear/finalize. |
| `openmdao_api_problem` | `local_full` | `openmdao.api` | Root-package ingestion around `Problem` setup and inspection flows. |
| `openmdao_file_utils` | `gha_subset` | `openmdao.utils.file_utils` | Concrete utility-function wrapping against a checked-in demo package. |
| `pynastran_bdf` | `gha_subset` | `pyNastran.bdf.bdf` | Class scaffolding that creates model content and writes a non-empty deck. |
| `su2_cli` | `local_full` | `SU2_CFD` | Live CLI ingestion against a tiny adapted tutorial case. |
| `submitit_root` | `local_full` | `submitit` | Executor lifecycle wrapping for both local and auto executors. |
| `xfoil_cli` | `local_full` | `xfoil` | CLI ingestion around a batch polar-generation workflow. |

Run the reduced suite, the broader local suite, or one case in isolation:

```bash
make challenge-deps
make challenges-subset
make challenges-full
make challenge CASE=openmdao_file_utils
```

The broader live challenge track lives in [challenges/README.md](challenges/README.md).
The separate case-study lane lives in [case_studies/README.md](case_studies/README.md).

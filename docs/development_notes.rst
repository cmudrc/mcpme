Development Notes
=================

These notes track the current deterministic ingestion architecture. They are
meant for contributors, not as a public API contract.

Scaffolding Strategy
--------------------

`mcpme` keeps the supported top-level API intentionally small. Rather than
exposing a large ingestion framework at the package root, stage-1 one-shot
ingestion works by generating plain Python facade modules through CLI commands:

- ``mcpme scaffold-package`` for installed Python packages or modules
- ``mcpme scaffold-command`` for standalone CLI tools
- ``mcpme scaffold-openapi`` for OpenAPI-described HTTP surfaces

Those generated files are inspectable artifacts. Once written, they flow
through the same deterministic discovery, schema generation, execution, and MCP
runtime layers as handwritten wrappers.

Why This Shape
--------------

This design makes a few deliberate tradeoffs:

- Keep the public Python API small while still solving real ingestion problems.
- Preserve visibility into what was inferred by writing checked-in or
  reviewable facade modules.
- Reuse the existing source-first discovery stack instead of building parallel
  runtime pathways for every source type.
- Allow users to edit or curate the generated wrapper after the deterministic
  pass without losing provenance.
- Be explicit about trust boundaries. Package scaffolding imports inspected
  modules, CLI scaffolding runs ``--help``, and OpenAPI scaffolding reads local
  specs. Each one writes a reviewable adapter artifact before normal discovery.

Current Internal Modules
------------------------

- The private package-and-command scaffolding module handles installed-package
  scaffolding and CLI-command scaffolding.
- The private OpenAPI scaffolding module handles OpenAPI-to-Python facade
  generation.
- The private source-first discovery engine remains the parser used after
  scaffolding completes.

Guidelines
----------

- Generated wrapper docstrings should be rich, explicit, and source-aware.
- Prefer deterministic fallbacks over fragile magic. For example, when CLI help
  parsing is ambiguous, emit an ``argv`` passthrough wrapper instead of guessing.
- Preserve artifact trust: subprocess and HTTP wrappers should return
  inspectable structured records, not opaque success strings.
- Avoid adding new top-level exports unless the behavior proves broadly useful
  outside the scaffold pipeline itself.

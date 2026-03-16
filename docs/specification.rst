MCP Wrapper Specification
=========================

This document is the first-pass product and implementation spec for a
pip-installable library, tentatively named ``mcpme``, that turns existing
engineering tools into MCP servers with minimal handwritten glue.

Status
------

This is a working draft. It captures the intended direction for the repository,
not a frozen contract.

Problem Statement
-----------------

Engineering teams already have useful tools in several forms:

* Python libraries with a small public API
* Single scripts or a directory of related scripts
* CLI entry points that already express a stable command surface

Most of these tools are not exposed as MCP servers, which means teams either
write one-off wrappers by hand or never make the tools available to MCP-aware
clients at all.

The library should make that wrapping cheap and predictable. The central idea
is that we can derive most MCP tool metadata from deterministic inspection of
the wrapped target's public interface, especially its type hints and docstrings,
instead of relying on runtime guesswork or AI-based interpretation.

For engineering and scientific computing in particular, the project should
assume that the wrapped tool is often the trusted asset. The goal is usually to
preserve validated code and expose it safely, not to replace it with a less
deterministic layer.

Goals
-----

* Make existing engineering tools MCP-exposable with little or no wrapper code.
* Preserve validated legacy and heritage tools instead of forcing rewrites.
* Prefer deterministic, reproducible inspection over heuristic inference.
* Generate MCP tool definitions from public interfaces, type hints, and
  docstrings.
* Keep the base install small and standard-library-first where practical.
* Support both library use and a CLI for local inspection and serving.
* Produce a stable intermediate manifest that can be tested before a server is
  launched.
* Preserve enough execution evidence that engineers can inspect what actually
  ran and build trust in the wrapper.

Non-Goals
---------

* Full automatic understanding of arbitrary shell scripts or binaries.
* Replacing deterministic engineering codes with LLM-mediated computation.
* Any AI or LLM dependency in the first pass of the project.
* Supporting every docstring style in v1.
* Hiding ambiguous behavior instead of surfacing it as an explicit error or
  override requirement.
* Automatically uploading source code, inputs, or outputs to external AI
  services as part of normal discovery or execution.
* Re-engineering stable legacy tools when a thin wrapper is sufficient.

Product Shape
-------------

The project should ship three closely related surfaces:

* A Python library for discovery, manifest generation, and server runtime
* A CLI for inspect/build/serve workflows
* An optional config file layer for overrides and non-inferable metadata

The most important internal boundary is between discovery and runtime:

* Discovery produces a canonical manifest for each tool candidate.
* Runtime binds each manifest entry to an executor and exposes it through MCP.

The runtime should be manifest-driven rather than wrapper-code-driven wherever
possible. In other words, the preferred scaling pattern is one generic engine
that hydrates behavior from explicit manifests, not one bespoke handwritten MCP
server per engineering tool.

Core Concepts
-------------

Source target
   The thing being wrapped. Examples: an importable Python module, a Python file
   path, a directory of scripts, or a named CLI command.

Tool candidate
   A public callable or command that may become an MCP tool.

Manifest
   The deterministic intermediate representation produced by discovery. It
   contains canonical tool metadata, JSON Schema, execution hints, and source
   references.

Binding
   The runtime association between a manifest entry and the callable or command
   that actually executes the work.

Override
   User-supplied configuration that fills gaps or resolves ambiguity without
   changing the wrapped source.

Design Principles
-----------------

Python-first
   V1 should focus on Python libraries and Python scripts, because those targets
   expose signatures, annotations, and docstrings in a structured way.

Static-first
   Discovery should prefer source parsing with ``ast`` when source is available,
   then fall back to runtime reflection only when necessary.

Public-interface-first
   Discovery should expose only explicitly public surfaces, never private helpers
   by default.

Overrides win
   Explicit configuration always takes precedence over inferred metadata.

Fail closed on ambiguity
   When a signature, type, or docstring cannot be mapped reliably, discovery
   should raise a precise error instead of silently guessing.

Wrap, do not rewrite
   The wrapper should preserve the original tool as the computational source of
   truth whenever feasible, especially for validated engineering codes.

Artifacts are first-class
   Input decks, rendered config files, stdout, stderr, output files, and parsed
   summaries are all part of the trust story and should be treated as deliberate
   outputs of the wrapper layer.

Thin control plane
   The wrapper should add as little execution overhead as practical so the
   underlying engineering tool remains the main performance determinant.

Least exposure
   Servers should expose only the tools relevant to the current deployment or
   task so MCP clients are not flooded with irrelevant capabilities.

Supported Inputs
----------------

Phase 1 input kinds:

* Importable Python modules or packages
* Python file paths
* Directories containing Python scripts
* Explicitly registered Python callables
* Standalone CLI commands wrapped through generated facades
* OpenAPI JSON or YAML documents wrapped through generated facades

Phase 2 input kinds:

* Non-Python executables paired with explicit config
* JSON Schema or protobuf-described tools
* Workflow descriptors such as CWL, WDL, Nextflow, Snakemake, or Galaxy tool specifications

For opaque shell scripts or binaries, the library should not pretend to infer a
rich schema from help text alone. Those targets should require sidecar metadata
or an explicit adapter.

Support Matrix
--------------

The deterministic baseline should support several source styles, but not all in
the same way. Some targets can be discovered natively, while others should be
wrapped through explicit manifests or sidecar configuration.

Typed Python libraries
   Native support in stage 1. Discover from modules, packages, files, and
   directly registered callables.

Python CLIs built with ``argparse``
   Native support in stage 1 when the parser object and command prefix are
   explicitly registered.

Python CLIs built with Click or Typer
   Deterministic support path in stage 1 through generated subprocess-backed
   facades created from CLI help output. Native framework introspection can be
   added later as a deterministic adapter.

Config-file-driven executables
   Native support in stage 1 through manifest-driven subprocess wrappers with
   deterministic hydration and dehydration rules.

Legacy FORTRAN, C, or C++ batch tools
   Native support path in stage 1 through sidecar manifests that define command
   invocation, file rendering, and result extraction.

Containerized engineering tools
   Native support path in stage 1 by treating container entrypoints as
   subprocess tools with explicit command prefixes and artifact policies.

Post-processors, converters, and report parsers
   Native support in stage 1 through Python wrappers or subprocess manifests.

Parameter studies and optimization drivers
   Native support in stage 1 when the driver already exposes a callable or a
   stable command contract.

HPC job-backed tools
   Native support path in stage 1 through manifest-driven submission commands,
   though cluster-specific adapters may be added later.

OpenAPI, JSON Schema, or protobuf-described tools
   OpenAPI is supported in stage 1 through generated HTTP facades. JSON Schema
   and protobuf remain deterministic adapter targets for later work.

Workflow descriptors such as CWL, WDL, Nextflow, Snakemake, or Galaxy tool specifications
   Deterministic adapter target for later work. The first-pass runtime should
   instead focus on the lower-level manifest and subprocess execution model.

Deterministic Escalation Policy
-------------------------------

The first pass of the project should be fully non-AI. Discovery, manifest
generation, translation, execution, and validation should all be achievable with
deterministic techniques.

Resolution order for v1:

1. Explicit registration or sidecar config
2. Static source parsing
3. Runtime reflection against local code objects
4. Deterministic sandboxed execution with fixture inputs
5. Human-supplied metadata or review

Rules:

* Steps 1 through 5 define the complete first-pass product.
* If these steps do not yield a trustworthy wrapper, the target is out of scope
  until more deterministic support is added.
* Any later-stage AI-assisted feature must sit downstream of deterministic
  manifest generation and deterministic verification.
* Later-stage AI-assisted flows must be opt-in and local-policy-aware.

Discovery Pipeline
------------------

Discovery should be deterministic and testable. The proposed pipeline is:

1. Resolve the source target kind.
2. Enumerate public tool candidates using target-specific rules.
3. Harvest signatures, annotations, docstrings, and source locations.
4. Normalize names and descriptions into a canonical manifest entry.
5. Build input and output schemas from supported type information.
6. Apply overrides from config or explicit registration.
7. Validate the final manifest and surface any unsupported constructs.

Each step should produce inspectable intermediate data so failures are easy to
debug.

For source types that are not natively executable Python functions, discovery
may begin with a deterministic scaffolding step that writes a plain Python
facade module first. That generated file is then discovered like any other
source-backed wrapper, which keeps the ingestion boundary inspectable and
reviewable.

Public Discovery Rules
----------------------

Importable Python module or package
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Discovery precedence should be:

1. Explicit object list supplied by the caller or config
2. Names listed in ``__all__``, in declared order
3. Top-level callables whose names do not start with ``_``, sorted by name

Python file path
^^^^^^^^^^^^^^^^

Discovery should parse the file with ``ast`` and collect top-level function
definitions whose names do not start with ``_``. Runtime binding may import or
execute the module later, but discovery should not require executing arbitrary
user code when source is available.

Directory of Python scripts
^^^^^^^^^^^^^^^^^^^^^^^^^^^

Discovery should treat each ``*.py`` file as a module-like source target. The
default rule should expose one or more public top-level functions per file.

Registered callables
^^^^^^^^^^^^^^^^^^^^

The library should allow direct registration of a callable object for cases
where discovery has already happened elsewhere or where a user wants full
programmatic control.

Generated package facades
^^^^^^^^^^^^^^^^^^^^^^^^^

For installed packages that are not already organized around a small function
surface, the CLI may generate a facade module that:

* wraps public functions directly,
* wraps public classes through explicit create, method, and close tools, and
* preserves source references and docstring summaries in generated code.

Because this flow inspects live importable objects, it necessarily imports the
target package or selected submodules during scaffolding. The generated facade
is therefore the reviewable artifact that freezes the inferred interface before
normal manifest generation and serving.

Generated CLI facades
^^^^^^^^^^^^^^^^^^^^^

Standalone CLI tools may be ingested through a generated facade module that:

* captures deterministic help text from the target command,
* maps stable options and positionals into named Python parameters when the
  help contract is clear, and
* falls back to an explicit ``argv`` passthrough wrapper when the CLI surface
  is too ambiguous to name safely.

This keeps one-shot CLI ingestion useful without pretending that arbitrary
shell help text is a perfect schema language.

Generated OpenAPI facades
^^^^^^^^^^^^^^^^^^^^^^^^^

OpenAPI documents may be ingested through a generated facade module that:

* resolves local ``#/...`` references,
* generates one Python function per supported operation,
* maps path, query, header, and cookie parameters into named inputs, and
* preserves the HTTP method, path, and default base URL in generated code.

The generated module becomes the inspectable adapter artifact. Runtime
execution then flows through normal Python discovery and generic execution
rules instead of a separate OpenAPI-only runtime.

V1 exclusions
^^^^^^^^^^^^^

The following should be rejected unless wrapped by an explicit adapter:

* Positional-only parameters
* Bare ``*args`` or ``**kwargs``
* Callables with no stable import path and no direct registration
* Callables whose annotations cannot be mapped to JSON Schema

Docstring Contract
------------------

V1 should treat Sphinx field-list docstrings as the canonical structured
format, because they align naturally with Sphinx autodoc output and remain
straightforward to parse deterministically.

Docstrings serve three roles:

* Summary paragraph becomes the default tool description.
* ``:param name:`` entries become parameter descriptions.
* ``:returns:`` becomes output description metadata.

An optional ``MCP:`` section should provide extra wrapper-specific metadata
without requiring decorators or framework lock-in.

Example:

.. code-block:: python

   def mesh_model(input_path: str, target_size_mm: float) -> dict[str, str]:
       """Generate a finite-element mesh for a CAD model.

       :param input_path: Path to the source CAD file.
       :param target_size_mm: Desired global element size.
       :returns: A summary containing the written mesh path and element count.

       MCP:
           title: Mesh CAD Model
           read_only: false
           destructive: false
           idempotent: true
           open_world: false
       """

Supported ``MCP:`` keys in v1 should be:

* ``title``
* ``name``
* ``read_only``
* ``destructive``
* ``idempotent``
* ``open_world``
* ``hidden``

Unknown keys should produce a validation error so the contract stays tight.

Schema Generation
-----------------

The manifest should carry JSON Schema for inputs and, when possible, outputs.

Supported input type mappings in v1:

* ``str`` -> string
* ``int`` -> integer
* ``float`` -> number
* ``bool`` -> boolean
* ``bytes`` -> base64-encoded string
* ``Path`` -> string with deterministic path metadata
* ``list[T]`` and ``tuple[T, ...]`` -> array
* ``dict[str, T]`` -> object with ``additionalProperties``
* ``Literal[...]`` and ``Enum`` -> enum
* ``T | None`` -> optional field
* ``Annotated[T, ...]`` -> ``T`` plus deterministic schema metadata
* ``TypedDict`` -> object schema
* ``dataclass`` -> object schema

Notes:

* Parameter descriptions come from the docstring when available.
* Required fields are derived from the Python signature.
* Defaults are copied from the Python signature when JSON-serializable.
* Annotated path metadata should be preserved for file and directory intent.
* Unsupported annotations should raise an explicit discovery error.

Output handling in v1 should follow these rules:

* If the return annotation maps cleanly to JSON Schema, emit ``outputSchema``.
* If a tool returns structured data, return both ``structuredContent`` and a
  JSON text mirror for compatibility.
* If a tool returns plain text, return a single text content block.
* Explicit subprocess adapters may surface binary files and directory manifests
  deterministically.

Manifest Shape
--------------

The internal manifest should be a stable, serializable object. At minimum each
entry should contain:

* Canonical MCP tool name
* Optional title
* Description
* Input schema
* Optional output schema
* Behavioral hints
* Optional deterministic aliases
* Source reference
* Binding strategy
* Validation warnings or errors

Keeping the manifest explicit lets users review generated tools before serving
them and gives us a clean seam for tests.

For legacy executables and script collections, the manifest should also be able
to describe hydration and dehydration behavior as data. That keeps adapter logic
inspectable and allows a generic runtime to execute many tools without a custom
server for each one.

Hydration and Dehydration
-------------------------

Many engineering tools do not accept native JSON inputs or produce native JSON
outputs. The wrapper therefore needs a deterministic translation layer.

Hydration is the process of turning structured MCP tool arguments into the
actual invocation format expected by the underlying tool, such as:

* CLI arguments
* Environment variables
* Fixed-format text files
* INI-like or NAMELIST-style configuration files
* Standard input streams

Dehydration is the reverse process of converting tool outputs into concise,
structured results by combining:

* Declared file locations
* Deterministic text parsing
* Regex extraction where appropriate
* Layout-aware parsers when output formats are semi-structured
* Explicit result mappers for known file formats

V1 should support only deterministic hydration and dehydration rules. A wrapper
should never depend on an AI system to understand what input file to write or
how to parse a report in the normal path.

Runtime Model
-------------

The runtime should read a validated manifest and expose MCP tools with the
current protocol shape: ``name``, optional ``title``, ``description``,
``inputSchema``, optional ``outputSchema``, and optional behavioral
``annotations`` as defined by the MCP tools spec_.

Execution should follow this flow:

1. Receive a tool call.
2. Validate arguments against the manifest schema.
3. Convert validated JSON values into the bound Python call signature.
4. Execute the underlying callable or command.
5. Persist invocation and execution records when retention is enabled.
6. Normalize the result into MCP tool result content plus deterministic
   ``_meta`` execution details.

Error handling should separate protocol errors from execution errors:

* Unknown tools and invalid arguments should surface as request-level errors.
* Underlying tool failures should return a tool result with ``isError: true``.
* Result extraction failures should preserve the underlying invocation record
  instead of hiding it behind a generic filesystem exception.

Behavioral hints should map from docstrings or overrides to MCP
``annotations``. The first-pass mapping should cover:

* ``read_only`` -> ``readOnlyHint``
* ``destructive`` -> ``destructiveHint``
* ``idempotent`` -> ``idempotentHint``
* ``open_world`` -> ``openWorldHint``

Artifact Retention and Trust
----------------------------

To make wrapped engineering tools inspectable and trustworthy, the runtime
should retain or optionally retain execution artifacts in a predictable
directory structure.

Per invocation, the wrapper should be able to capture:

* Manifest version or hash
* Resolved tool name and binding
* Validated input arguments
* Rendered input files or command-line arguments
* Working directory
* Start and end timestamps
* Duration and exit code
* Timeout and cancellation status
* Standard output and standard error
* Declared output files
* Explicitly retained output files or directories
* Parsed structured summary returned to the MCP client

This serves several purposes:

* Engineers can see exactly what the agent ran.
* Runs become easier to reproduce outside the MCP environment.
* Debugging does not depend on opaque model reasoning.
* Trust increases because familiar I/O artifacts remain visible.

Retention settings should be configurable so sensitive data can be minimized or
redacted when necessary.

The MCP-facing result should also include deterministic ``_meta`` fields with:

* Local artifact directory path
* Artifact listing with sizes and relative paths
* Execution summary including duration, exit status, and retained outputs

Configuration Model
-------------------

The library should support both embedded and standalone TOML configuration so it
works well for packages and loose script collections.

Preferred locations:

* ``pyproject.toml`` under ``[tool.mcpme]``
* ``mcpme.toml`` for non-package repos

Config should be used for:

* Explicit target lists
* Renaming tools
* Hiding or excluding candidates
* Selecting Python discovery mode
* Supplying metadata that cannot be inferred deterministically
* Selecting transport and runtime options
* Declaring hydration and dehydration strategies for non-native interfaces
* Declaring artifact retention and redaction policy
* Declaring explicit retained output paths for subprocess tools

Example:

.. code-block:: toml

   [tool.mcpme]
   targets = ["acme.fea", "scripts/mesh.py"]
   transport = "stdio"
   python_discovery_mode = "source"

   [tool.mcpme.tool.mesh_model]
   title = "Mesh CAD Model"
   read_only = false
   destructive = false
   idempotent = true
   open_world = false

Candidate Public API
--------------------

The curated top-level API should stay intentionally small. Advanced config and
manifest-model details can live in submodules until they prove they need a
stable top-level contract.

The current intended top-level surface is:

.. code-block:: python

   from mcpme import (
       ArgparseCommand,
       build_manifest,
       execute_tool,
       Manifest,
       McpServer,
       serve_stdio,
   )

   manifest = build_manifest(
       targets=["acme.fea", "scripts/mesh.py"],
       config_path="pyproject.toml",
   )
   result = execute_tool(manifest, "mesh_model", {"input_path": "wing.step"})
   server = McpServer(manifest)
   serve_stdio(manifest)

Candidate CLI commands:

* ``mcpme inspect <target>``
* ``mcpme manifest <target>``
* ``mcpme serve <target>``
* ``mcpme scaffold-package <package> <output.py>``
* ``mcpme scaffold-command <output.py> -- <command ...>``
* ``mcpme scaffold-openapi <spec.json> <output.py>``

The CLI should expose the same discovery engine as the Python library instead of
maintaining a parallel implementation.

Safety and Trust
----------------

The runtime should assume that wrapped tools may be powerful and potentially
destructive.

Requirements:

* Validate all tool inputs before execution.
* Support per-tool timeouts.
* Allow environment-variable and working-directory restrictions.
* Make destructive behavior explicit through hints and config.
* Avoid shell interpolation unless an adapter explicitly opts into it.
* Keep background jobs inspectable, cancellable, and locally persistent.

This aligns with the MCP guidance that tool use should preserve human oversight
and clear visibility into what a tool can do and when it is invoked.

Privacy and IP Boundaries
-------------------------

Because many wrapped tools encode sensitive engineering know-how, the default
system posture should be local-first and non-exfiltrating.

Requirements:

* Discovery and execution should operate locally by default.
* The first pass should have no external AI integration at all.
* Source code, build artifacts, inputs, and outputs should not be sent to an
  external AI provider unless a user explicitly enables that behavior.
* Any future AI-assisted mode should document exactly what data leaves the local
  environment.
* Redaction hooks should exist for logs and retained artifacts.

Phased Delivery
---------------

Stage 1: deterministic baseline
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Phase 0: discovery only
   Build the manifest generator for Python modules, files, and registered
   callables. No server runtime yet.

Phase 1: minimal MCP runtime
   Serve a validated manifest over stdio for Python-backed tools.

Phase 2: deterministic translation and auditability
   Add TOML-based overrides, hydration and dehydration rules, structured
   artifact capture, retained output rules, and source-first discovery.

Phase 3: legacy adapters and selective exposure
   Add carefully scoped executable adapters, sidecar manifests for legacy
   binaries, deployment-time tool filtering to avoid context pollution, and
   deterministic background job control for long-running subprocess tools.

Stage 2: optional post-generation cleanup
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

After the deterministic baseline exists, a later stage may experiment with a
coding LLM as a cleanup or refactoring assistant for generated wrapper code.

Constraints for that stage:

* The deterministic manifest remains the source of truth.
* Generated code must still pass deterministic validation and tests.
* AI output may improve readability, factoring, or documentation, but must not
  be the source of interface inference.
* Stage 2 is optional and should not change the core non-AI path.

Open Questions
--------------

* Should v1 expose class instance methods at all, or require a decorator or
  registration step?
* Should discovery preserve module source order when ``__all__`` is absent, or
  sort alphabetically for maximum stability?
* Do we want a decorator for explicit opt-in, or should config be the only
  override mechanism in the first version?
* How aggressively should we emit ``outputSchema`` versus falling back to text
  results?
* What should the default artifact-retention policy be for potentially sensitive
  engineering inputs and outputs?
* If stage 2 introduces coding-LLM cleanup, what semantic boundaries must remain
  locked so the cleanup step cannot alter tool behavior?

Protocol References
-------------------

The MCP-facing language in this spec assumes the current official tool model,
including tool ``title``, ``inputSchema``, ``outputSchema``,
``structuredContent``, and ``annotations`` support in the 2025-06-18
specification.

.. _spec: https://modelcontextprotocol.io/specification/2025-06-18/server/tools

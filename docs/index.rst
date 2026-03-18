mcpme
=====

`mcpme` is a deterministic Python library for exposing engineering tools as
MCP servers. It focuses on manifest-driven wrappers, predictable discovery, and
inspectable execution artifacts rather than AI-based interface inference.

It is built for teams that want wrappers they can inspect and trust:

- discover public interfaces without guessing
- preserve the underlying tool, files, and execution evidence
- generate plain Python facades for packages, CLIs, OpenAPI specs, and
  batch-style subprocess tools

The checked-in examples and case studies keep their preset support inputs in
source control and reserve ``artifacts/`` for derived outputs only. The case
studies go a step further and split each walkthrough into ingest, serve, and
use phases so the generated facade remains directly inspectable and testable as
an MCP server.

Start Here
----------

- :doc:`Quickstart <quickstart>` for the fastest end-to-end path
- :doc:`Examples <examples/index>` for runnable patterns
- :doc:`Case Studies <case_studies/index>` for richer optional upstream walkthroughs
- :doc:`API <api>` for the supported public surface
- :doc:`Specification <specification>` for the deterministic contract

.. toctree::
   :hidden:
   :maxdepth: 1

   Quickstart <quickstart>
   Examples <examples/index>
   Case Studies <case_studies/index>
   API <api>
   Spec <specification>
   Notes <development_notes>
   Dependencies <dependencies_and_extras>

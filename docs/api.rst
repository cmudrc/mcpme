API
===

This page documents the supported top-level public API exported from the package
root.

Compatibility guarantees apply to these root imports. Internal underscored
modules remain implementation details and are intentionally excluded from the
supported surface.

Public Surface
--------------

Core Entry Points
^^^^^^^^^^^^^^^^^

``build_manifest`` is the main deterministic discovery entry point.
``execute_tool`` runs one manifest tool through the generic execution engine.
``serve_stdio`` exposes a manifest through a small stdio MCP runtime.

.. autofunction:: mcpme.build_manifest

.. autofunction:: mcpme.execute_tool

.. autofunction:: mcpme.serve_stdio

Runtime
^^^^^^^

``McpServer`` is the in-process JSON-RPC runtime facade. It is the smallest
useful runtime object for tests, embedding, and custom launchers.

.. autoclass:: mcpme.McpServer
   :members:
   :undoc-members:

Contracts
^^^^^^^^^

``Manifest`` and ``ToolExecutionResult`` are the two primary user-facing data
contracts at runtime: one describes what can be exposed, and the other
describes what happened when a tool ran.

.. autoclass:: mcpme.Manifest
   :members:
   :undoc-members:

.. autoclass:: mcpme.ToolExecutionResult
   :members:
   :undoc-members:

Registration Helpers
^^^^^^^^^^^^^^^^^^^^

``ArgparseCommand`` is the only top-level configuration helper currently
exported. It keeps the public API small while still covering a common source of
deterministic CLI metadata.

.. autoclass:: mcpme.ArgparseCommand
   :members:
   :undoc-members:

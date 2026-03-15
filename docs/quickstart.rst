Quickstart
==========

`mcpme` targets Python 3.12+ and assumes a standard `src/` layout.

Local development setup:

.. code-block:: bash

   python -m venv .venv
   source .venv/bin/activate
   make dev
   make test
   make run-examples

Run the bundled example:

.. code-block:: bash

   make run-example

Inspect a target with the CLI:

.. code-block:: bash

   mcpme inspect examples/basic_usage.py

Generate inspectable facades when the source surface is a package, standalone
CLI, or OpenAPI spec:

.. code-block:: bash

   mcpme scaffold-package some_package artifacts/generated_package.py
   mcpme scaffold-command artifacts/generated_cli.py -- tool
   mcpme scaffold-openapi api.json artifacts/generated_api.py

`mcpme` discovers Python files and source-backed modules without importing them
by default. Discovery reads signatures, annotations, and docstrings from source
and defers imports until execution time.

The three scaffold flows have deliberately explicit trust boundaries:

- ``scaffold-package`` imports the target package or selected submodules, then
  writes a plain Python facade that can be reviewed before serving.
- ``scaffold-command`` executes the target command with ``--help`` and only
  names inputs when the help surface is deterministic enough to parse safely.
- ``scaffold-openapi`` reads the local OpenAPI document and generates a plain
  Python HTTP facade rather than introducing a separate opaque runtime path.

Standalone subprocess tools are configured explicitly in TOML. A minimal
example that retains a report directory looks like:

.. code-block:: toml

   [tool.mcpme]
   artifact_mode = "summary"
   python_discovery_mode = "source"

   [[tool.mcpme.subprocess]]
   name = "emit_artifacts"
   description = "Render an input file and retain a report directory."
   argv = ["python", "emit_artifacts.py", "input.json"]
   result_kind = "file_bytes"
   result_path = "report.bin"

   [tool.mcpme.subprocess.input_schema]
   type = "object"
   required = ["message"]

   [tool.mcpme.subprocess.input_schema.properties.message]
   type = "string"

   [[tool.mcpme.subprocess.files]]
   path = "input.json"
   template = "{{\"message\": \"{message}\"}}"

   [[tool.mcpme.subprocess.outputs]]
   path = "reports"
   kind = "directory"
   when = "success"

Long-running subprocess tools can also be started in background mode through
``tools/call`` by adding ``_meta = {"mcpme/runMode": "async"}`` to the request
params. The runtime then exposes ``mcpme/jobs/list``, ``mcpme/jobs/get``,
``mcpme/jobs/tail``, and ``mcpme/jobs/cancel`` for deterministic job control.

Build the docs:

.. code-block:: bash

   make docs

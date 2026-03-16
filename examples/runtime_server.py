"""Runnable example for the minimal in-process MCP runtime.

## Introduction

This example demonstrates the smallest practical MCP runtime loop you can build
with `mcpme`. It keeps the public API surface small: build a manifest, hand it
to :class:`mcpme.McpServer`, and exchange JSON-RPC messages.

## Technical Implementation

- Define a typed callable that represents a small engineering status query.
- Build a manifest from that callable.
- Send `initialize`, `tools/list`, and `tools/call` requests through
  :class:`mcpme.McpServer`.
- Expose an opt-in `--stdio` path that delegates to :func:`mcpme.serve_stdio`
  for a real stdio runtime.

## Expected Results

Running this script without arguments prints three JSON-RPC responses. Running
it with `--stdio` turns the process into a tiny MCP server for the same tool.

## References

- ``README.md``
- ``docs/api.rst``
- ``docs/quickstart.rst``
"""

from __future__ import annotations

import json
import sys

from mcpme import Manifest, McpServer, build_manifest, serve_stdio


def inspect_case(case_name: str) -> dict[str, str]:
    """Return a deterministic engineering case summary.

    :param case_name: Case identifier to inspect.
    :returns: A small status payload.

    MCP:
        title: Inspect Case
        read_only: true
        idempotent: true
    """
    return {"case_name": case_name, "status": "ready"}


def build_runtime_manifest() -> Manifest:
    """Build the manifest used by the runtime example."""
    return build_manifest(targets=[inspect_case])


def run_request_demo() -> list[dict[str, object] | None]:
    """Send a few JSON-RPC messages through the in-process runtime."""
    server = McpServer(build_runtime_manifest())
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "inspect_case", "arguments": {"case_name": "wing_box"}},
        },
    ]
    return [server.handle_request(request) for request in requests]


def run_stdio_server() -> None:
    """Serve the example manifest over stdio until the client disconnects."""
    serve_stdio(build_runtime_manifest())


def main(argv: list[str] | None = None) -> None:
    """Run the request demo or opt into stdio server mode."""
    args = argv if argv is not None else sys.argv[1:]
    if "--stdio" in args:
        run_stdio_server()
        return
    print(json.dumps(run_request_demo(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

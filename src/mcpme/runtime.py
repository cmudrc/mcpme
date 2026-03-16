"""Minimal deterministic MCP runtime over JSON-RPC."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import Any, TextIO

from ._jobs import JobManager
from .execution import execute_tool
from .manifest import Manifest


@dataclass(slots=True)
class McpServer:
    """Serve deterministic manifest tools through a small JSON-RPC surface.

    :param manifest: Loaded manifest exposed through the runtime.
    """

    manifest: Manifest
    job_manager: JobManager | None = None

    def __post_init__(self) -> None:
        """Initialize the deterministic background job manager."""
        self.job_manager = JobManager(self.manifest)

    def handle_request(self, request: dict[str, Any]) -> dict[str, Any] | None:
        """Handle one JSON-RPC request object.

        :param request: Parsed JSON-RPC request payload.
        :returns: A JSON-RPC response payload, or ``None`` for notifications.
        """
        method = request.get("method")
        request_id = request.get("id")
        try:
            if method == "initialize":
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {
                            "tools": {},
                            "experimental": {
                                "mcpmeJobs": {
                                    "methods": [
                                        "mcpme/jobs/list",
                                        "mcpme/jobs/get",
                                        "mcpme/jobs/tail",
                                        "mcpme/jobs/cancel",
                                    ]
                                }
                            },
                        },
                        "serverInfo": {"name": "mcpme", "version": "0.1.0"},
                    },
                }
            if method == "notifications/initialized":
                return None
            if method == "tools/list":
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {"tools": [tool.to_mcp_tool() for tool in self.manifest.tools]},
                }
            if method == "tools/call":
                params = request.get("params", {})
                meta = params.get("_meta", {}) if isinstance(params, dict) else {}
                run_mode = meta.get("mcpme/runMode")
                if run_mode == "async":
                    if self.job_manager is None:
                        raise RuntimeError("Job manager is not initialized.")
                    job = self.job_manager.start(
                        str(params["name"]),
                        dict(params.get("arguments", {})),
                    )
                    return {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": f"Started job {job['jobId']} for {job['tool']}.",
                                }
                            ],
                            "_meta": {"mcpme/job": job},
                        },
                    }
                result = execute_tool(
                    self.manifest,
                    str(params["name"]),
                    dict(params.get("arguments", {})),
                )
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": result.to_mcp_result(),
                }
            if method == "mcpme/jobs/list":
                if self.job_manager is None:
                    raise RuntimeError("Job manager is not initialized.")
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {"jobs": self.job_manager.list_jobs()},
                }
            if method == "mcpme/jobs/get":
                if self.job_manager is None:
                    raise RuntimeError("Job manager is not initialized.")
                params = request.get("params", {})
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": self.job_manager.get(str(params["jobId"])),
                }
            if method == "mcpme/jobs/tail":
                if self.job_manager is None:
                    raise RuntimeError("Job manager is not initialized.")
                params = request.get("params", {})
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": self.job_manager.tail(
                        str(params["jobId"]),
                        stream=str(params.get("stream", "stdout")),
                        lines=int(params.get("lines", 100)),
                    ),
                }
            if method == "mcpme/jobs/cancel":
                if self.job_manager is None:
                    raise RuntimeError("Job manager is not initialized.")
                params = request.get("params", {})
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": self.job_manager.cancel(str(params["jobId"])),
                }
            return self._error_response(request_id, -32601, f"Unknown method: {method}")
        except Exception as error:
            return self._error_response(request_id, -32000, str(error))

    def _error_response(self, request_id: object, code: int, message: str) -> dict[str, Any]:
        """Build a JSON-RPC error response."""
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        }


def serve_stdio(
    manifest: Manifest,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
) -> None:
    """Serve the minimal MCP runtime over stdio.

    :param manifest: Loaded manifest exposed through the stdio server.
    :param stdin: Optional input stream override.
    :param stdout: Optional output stream override.
    """
    input_stream = stdin or sys.stdin
    output_stream = stdout or sys.stdout
    server = McpServer(manifest)
    for line in input_stream:
        if not line.strip():
            continue
        response = server.handle_request(json.loads(line))
        if response is None:
            continue
        output_stream.write(json.dumps(response) + "\n")
        output_stream.flush()

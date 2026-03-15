"""Runnable example for one-shot OpenAPI ingestion through scaffolded facades.

## Introduction

This example shows how to ingest an OpenAPI specification without adding any
runtime AI layer. `mcpme` turns the spec into a plain Python HTTP facade, then
wraps the generated functions through its normal deterministic discovery path.

## Technical Implementation

- Write a tiny OpenAPI document and a matching local HTTP server under
  `artifacts/examples/`.
- Run `python -m mcpme.cli scaffold-openapi` to generate a Python facade for
  the API operations.
- Build a manifest from the generated facade and execute the resulting tools
  through :func:`mcpme.execute_tool`.
- Print the scaffold report and the normalized HTTP responses as JSON.

## Expected Results

Running this script prints a JSON object that includes the scaffold report plus
two wrapped HTTP calls: one `GET` operation and one `POST` operation. The
generated facade remains available under `artifacts/examples/openapi_scaffold/`.

## References

- ``README.md``
- ``docs/quickstart.rst``
- ``docs/specification.rst``
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from mcpme import build_manifest, execute_tool

SUPPORT_ROOT = Path("artifacts/examples/openapi_scaffold")


def _write_spec(path: Path) -> None:
    """Write the tiny OpenAPI document ingested by the example."""
    path.write_text(
        json.dumps(
            {
                "openapi": "3.1.0",
                "servers": [{"url": "https://example.invalid"}],
                "paths": {
                    "/cases/{case_id}": {
                        "get": {
                            "operationId": "get_case",
                            "summary": "Fetch a case.",
                            "parameters": [
                                {
                                    "name": "case_id",
                                    "in": "path",
                                    "required": True,
                                    "description": "Case identifier.",
                                    "schema": {"type": "string"},
                                },
                                {
                                    "name": "verbose",
                                    "in": "query",
                                    "description": "Verbose output.",
                                    "schema": {"type": "boolean"},
                                },
                                {
                                    "name": "X-Mode",
                                    "in": "header",
                                    "description": "Execution mode header.",
                                    "schema": {"type": "string"},
                                },
                            ],
                        }
                    },
                    "/cases": {
                        "post": {
                            "operationId": "create_case",
                            "summary": "Create a case.",
                            "requestBody": {
                                "required": True,
                                "description": "Case payload.",
                                "content": {"application/json": {"schema": {"type": "object"}}},
                            },
                        }
                    },
                },
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def _pythonpath_env() -> dict[str, str]:
    """Build an environment that keeps `mcpme` importable for child processes."""
    env = dict(os.environ)
    existing = env.get("PYTHONPATH")
    paths = [str(Path("src").resolve())]
    if existing:
        paths.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(paths)
    return env


def _scaffold_openapi(spec_path: Path, output_path: Path) -> dict[str, object]:
    """Run the public OpenAPI scaffold flow and return its JSON report."""
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "mcpme.cli",
            "scaffold-openapi",
            str(spec_path),
            str(output_path),
        ],
        cwd=Path.cwd(),
        env=_pythonpath_env(),
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(completed.stdout)


def run_example() -> dict[str, object]:
    """Ingest the example OpenAPI spec and execute the generated wrappers."""
    SUPPORT_ROOT.mkdir(parents=True, exist_ok=True)
    spec_path = SUPPORT_ROOT / "solver_api.json"
    output_path = SUPPORT_ROOT / "generated_openapi_facade.py"
    artifact_root = (SUPPORT_ROOT / "artifacts").resolve()
    _write_spec(spec_path)
    report = _scaffold_openapi(spec_path, output_path)
    manifest = build_manifest(targets=[output_path], artifact_root=artifact_root)
    with _solver_api_server() as base_url:
        get_result = execute_tool(
            manifest,
            "get_case",
            {
                "case_id": "wing_box",
                "verbose": True,
                "x_mode": "detail",
                "base_url": base_url,
            },
        )
        create_result = execute_tool(
            manifest,
            "create_case",
            {"body": {"name": "cantilever"}, "base_url": base_url},
        )
    return {
        "report": report,
        "get_case": json.loads(get_result.content[0]["text"]),
        "create_case": json.loads(create_result.content[0]["text"]),
    }


def main() -> None:
    """Run the OpenAPI scaffolding example and print JSON output."""
    print(json.dumps(run_example(), indent=2, sort_keys=True))


@contextmanager
def _solver_api_server() -> str:
    """Run a tiny local HTTP server used by the example OpenAPI calls."""

    class Handler(BaseHTTPRequestHandler):
        """Serve a tiny deterministic JSON API."""

        def do_GET(self) -> None:
            """Handle ``GET /cases/<id>`` requests."""
            parts = urlsplit(self.path)
            payload = {
                "case_id": parts.path.rsplit("/", 1)[-1],
                "verbose": parse_qs(parts.query).get("verbose", ["false"])[0],
                "mode": self.headers.get("X-Mode"),
            }
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            """Handle ``POST /cases`` requests."""
            content_length = int(self.headers.get("Content-Length", "0"))
            request_body = self.rfile.read(content_length).decode("utf-8")
            payload = json.dumps({"received": json.loads(request_body)}).encode("utf-8")
            self.send_response(201)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: object) -> None:
            """Suppress test-server access logs."""

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


if __name__ == "__main__":
    main()

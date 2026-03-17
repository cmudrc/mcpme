"""Tiny deterministic HTTP server used by the OpenAPI example."""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit


@contextmanager
def solver_api_server() -> str:
    """Run a tiny local HTTP server for the OpenAPI example."""

    class Handler(BaseHTTPRequestHandler):
        """Serve a tiny deterministic JSON API."""

        def do_GET(self) -> None:
            """Handle ``GET /cases/<id>`` requests."""
            parts = urlsplit(self.path)
            payload = {
                "case_id": parts.path.rsplit("/", 1)[-1],
                "mode": self.headers.get("X-Mode"),
                "verbose": parse_qs(parts.query).get("verbose", ["false"])[0],
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
            """Suppress access logs for the local test server."""

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

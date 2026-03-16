"""Tests for deterministic package, CLI, and OpenAPI scaffolding."""

from __future__ import annotations

import json
import sys
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from mcpme import build_manifest, execute_tool
from mcpme._openapi import scaffold_openapi
from mcpme._scaffold import scaffold_package
from mcpme.cli import main


def test_scaffold_package_generates_executable_facade(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    """Package scaffolding should yield runnable wrappers for functions and classes."""
    package_dir = tmp_path / "demo_pkg"
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text(
        '"""Demo package for scaffolding tests."""\n'
        "from .analysis import refine\n"
        "from .core import CounterSession, positional_solver, solve\n\n"
        '__all__ = ["solve", "positional_solver", "CounterSession", "refine"]\n',
        encoding="utf-8",
    )
    (package_dir / "core.py").write_text(
        '"""Core package tools."""\n\n'
        "def solve(mesh_size: int = 2) -> int:\n"
        '    """Solve a tiny deterministic case.\n\n'
        "    Args:\n"
        "        mesh_size: Mesh size.\n\n"
        "    Returns:\n"
        "        Scaled case score.\n"
        '    """\n'
        "    return mesh_size * 3\n\n\n"
        "def positional_solver(scale, /, offset=1):\n"
        '    """Exercise args/kwargs fallback wrapping.\n\n'
        "    Args:\n"
        "        scale: Scale input.\n"
        "        offset: Offset value.\n\n"
        "    Returns:\n"
        "        Combined result.\n"
        '    """\n'
        "    return scale + offset\n\n\n"
        "class CounterSession:\n"
        '    """Maintain a mutable counter.\n\n'
        "    Args:\n"
        "        start: Starting count.\n"
        '    """\n\n'
        "    def __init__(self, start: int = 0) -> None:\n"
        "        self.value = start\n\n"
        "    def increment(self, amount: int = 1) -> int:\n"
        '        """Increment the counter.\n\n'
        "        Args:\n"
        "            amount: Increment amount.\n\n"
        "        Returns:\n"
        "            Updated count.\n"
        '        """\n'
        "        self.value += amount\n"
        "        return self.value\n\n"
        "    def close(self) -> None:\n"
        "        self.value = -1\n",
        encoding="utf-8",
    )
    (package_dir / "analysis.py").write_text(
        '"""Analysis helpers."""\n\n'
        "def refine(level: int) -> int:\n"
        '    """Refine a deterministic level.\n\n'
        "    Args:\n"
        "        level: Refinement level.\n\n"
        "    Returns:\n"
        "        Refined level.\n"
        '    """\n'
        "    return level + 1\n",
        encoding="utf-8",
    )

    monkeypatch.syspath_prepend(str(tmp_path))

    output_path = tmp_path / "generated_package_facade.py"
    report = scaffold_package(
        "demo_pkg",
        output_path,
        include_submodules=True,
    )

    generated_names = {tool.name for tool in report.generated_tools}
    assert {
        "solve",
        "positional_solver",
        "refine",
        "create_counter_session",
        "counter_session_increment",
        "close_counter_session",
    } <= generated_names

    manifest = build_manifest(
        targets=[output_path],
        artifact_root=tmp_path / "artifacts",
    )

    solve_result = execute_tool(manifest, "solve", {"mesh_size": 4})
    assert json.loads(solve_result.content[0]["text"]) == 12

    positional_result = execute_tool(
        manifest,
        "positional_solver",
        {"args": [3], "kwargs": {"offset": 2}},
    )
    assert json.loads(positional_result.content[0]["text"]) == 5

    create_result = execute_tool(manifest, "create_counter_session", {"start": 10})
    session_record = json.loads(create_result.content[0]["text"])
    increment_result = execute_tool(
        manifest,
        "counter_session_increment",
        {"session_id": session_record["session_id"], "amount": 5},
    )
    assert json.loads(increment_result.content[0]["text"]) == 15

    close_result = execute_tool(
        manifest,
        "close_counter_session",
        {"session_id": session_record["session_id"]},
    )
    assert json.loads(close_result.content[0]["text"])["success"] is True


def test_scaffold_package_handles_docstring_escapes_enum_defaults_and_filters(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    """Package scaffolding should stay valid around raw docstrings and enum defaults."""

    package_dir = tmp_path / "filter_pkg"
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text(
        "from math import sqrt\n"
        "from .core import Mode, solve\n\n"
        '__all__ = ["Mode", "solve", "sqrt"]\n',
        encoding="utf-8",
    )
    (package_dir / "core.py").write_text(
        "from enum import Enum\n\n"
        "class Mode(Enum):\n"
        "    FINE = 'fine'\n\n"
        "def solve(mode: Mode = Mode.FINE) -> str:\n"
        '    """Solve a case with a Windows-style path like C:\\\\temp\\\\deck.inp.\n\n'
        "    Args:\n"
        "        mode: Solver mode.\n\n"
        "    Returns:\n"
        "        Selected mode.\n"
        '    """\n'
        "    return mode.value\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    output_path = tmp_path / "filtered_facade.py"
    report = scaffold_package(
        "filter_pkg",
        output_path,
        symbol_include_patterns=("^solve$", "^sqrt$"),
    )

    assert [tool.name for tool in report.generated_tools] == ["solve"]
    assert any(
        entry.reason == "function is re-exported from outside the target namespace"
        for entry in report.skipped
    )

    manifest = build_manifest(targets=[output_path], artifact_root=tmp_path / "artifacts")
    result = execute_tool(manifest, "solve", {})
    assert result.content[0]["text"] == "fine"


def test_cli_scaffold_command_generates_named_wrapper(
    tmp_path: Path,
    capsys: object,
) -> None:
    """CLI command scaffolding should parse argparse-style help into named inputs."""
    script_path = tmp_path / "beam_cli.py"
    script_path.write_text(
        "import argparse\n"
        "import json\n\n"
        "parser = argparse.ArgumentParser(description='Deterministic beam CLI.')\n"
        "parser.add_argument('job_name', help='Job label.')\n"
        "parser.add_argument('--scale', type=float, default=1.0, help='Scale factor.')\n"
        "parser.add_argument('--verbose', action='store_true', help='Verbose mode.')\n"
        "args = parser.parse_args()\n"
        "print(\n"
        "    json.dumps(\n"
        "        {'job_name': args.job_name, 'scale': args.scale, 'verbose': args.verbose}\n"
        "    )\n"
        ")\n",
        encoding="utf-8",
    )

    output_path = tmp_path / "generated_cli_facade.py"
    assert (
        main(
            [
                "scaffold-command",
                str(output_path),
                "--name",
                "run_beam_cli",
                "--",
                sys.executable,
                str(script_path),
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["targetKind"] == "command"
    assert report["generatedTools"][0]["style"] == "named"

    manifest = build_manifest(
        targets=[output_path],
        artifact_root=tmp_path / "artifacts",
    )
    tool = manifest.get_tool("run_beam_cli")
    assert tool.input_schema["properties"]["scale"]["anyOf"][0]["type"] == "number"
    assert tool.input_schema["properties"]["verbose"]["type"] == "boolean"

    result = execute_tool(
        manifest,
        "run_beam_cli",
        {"job_name": "cantilever", "scale": 2.5, "verbose": True},
    )
    assert json.loads(result.content[0]["text"])["stdout"].strip() == json.dumps(
        {"job_name": "cantilever", "scale": 2.5, "verbose": True}
    )


def test_cli_scaffold_command_accepts_custom_help_probe_args(
    tmp_path: Path,
    capsys: object,
) -> None:
    """CLI scaffolding should allow non-``--help`` probes for raw upstream tools."""

    script_path = tmp_path / "odd_help_cli.py"
    script_path.write_text(
        "import json\n"
        "import sys\n\n"
        "if '-h' in sys.argv[1:]:\n"
        "    print('usage: odd_help_cli.py --value VALUE')\n"
        "    print('\\noptions:')\n"
        "    print('  --value VALUE  Integer value.')\n"
        "    raise SystemExit(0)\n"
        "value = sys.argv[sys.argv.index('--value') + 1]\n"
        "print(json.dumps({'value': int(value)}))\n",
        encoding="utf-8",
    )

    output_path = tmp_path / "odd_help_facade.py"
    assert (
        main(
            [
                "scaffold-command",
                str(output_path),
                "--name",
                "run_odd_help_cli",
                "--help-probe-arg=-h",
                "--",
                sys.executable,
                str(script_path),
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["generatedTools"][0]["style"] == "named"

    manifest = build_manifest(targets=[output_path], artifact_root=tmp_path / "artifacts")
    result = execute_tool(manifest, "run_odd_help_cli", {"value": "7"})
    payload = json.loads(result.content[0]["text"])
    assert json.loads(payload["stdout"]) == {"value": 7}


def test_scaffold_openapi_generates_http_wrapper(tmp_path: Path) -> None:
    """OpenAPI scaffolding should yield runnable HTTP wrappers."""
    spec_path = tmp_path / "solver_api.json"
    spec_path.write_text(
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

    output_path = tmp_path / "generated_openapi_facade.py"
    report = scaffold_openapi(spec_path, output_path)
    assert {tool.name for tool in report.generated_tools} == {"create_case", "get_case"}

    manifest = build_manifest(
        targets=[output_path],
        artifact_root=tmp_path / "artifacts",
    )
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
        get_payload = json.loads(get_result.content[0]["text"])
        assert get_payload["body"]["case_id"] == "wing_box"
        assert get_payload["body"]["verbose"] == "true"
        assert get_payload["body"]["mode"] == "detail"

        create_result = execute_tool(
            manifest,
            "create_case",
            {"body": {"name": "cantilever"}, "base_url": base_url},
        )
        create_payload = json.loads(create_result.content[0]["text"])
        assert create_payload["status"] == 201
        assert create_payload["body"]["received"] == {"name": "cantilever"}


def test_cli_scaffold_package_and_openapi_emit_reports(
    tmp_path: Path,
    monkeypatch: object,
    capsys: object,
) -> None:
    """CLI package and OpenAPI scaffolding should emit deterministic JSON reports."""
    package_dir = tmp_path / "mini_pkg"
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text(
        "def solve(case_name: str) -> str:\n"
        '    """Solve a tiny case.\n\n'
        "    Args:\n"
        "        case_name: Case name.\n\n"
        "    Returns:\n"
        "        Case name.\n"
        '    """\n'
        "    return case_name\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    package_output = tmp_path / "mini_pkg_facade.py"
    assert main(["scaffold-package", "mini_pkg", str(package_output)]) == 0
    package_report = json.loads(capsys.readouterr().out)
    assert package_report["generatedTools"][0]["kind"] == "function"

    spec_path = tmp_path / "mini_api.json"
    spec_path.write_text(
        json.dumps(
            {
                "openapi": "3.1.0",
                "paths": {
                    "/health": {
                        "get": {
                            "operationId": "health",
                            "summary": "Read health state.",
                        }
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    openapi_output = tmp_path / "mini_api_facade.py"
    assert main(["scaffold-openapi", str(spec_path), str(openapi_output)]) == 0
    openapi_report = json.loads(capsys.readouterr().out)
    assert openapi_report["generatedTools"][0]["name"] == "health"


@contextmanager
def _solver_api_server() -> str:
    """Run a tiny local HTTP server used by OpenAPI scaffold tests."""

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

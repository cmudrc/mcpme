"""Tests for the minimal deterministic MCP runtime."""

from __future__ import annotations

import sys
import time
from pathlib import Path

from mcpwrap import McpServer, build_manifest


def test_runtime_lists_and_calls_tools(tmp_path: Path) -> None:
    """The in-process request handler should expose tools and execute them."""

    source = tmp_path / "text_tools.py"
    source.write_text(
        """def shout(message: str) -> str:\n"""
        '''    """Upper-case a message.\n\n'''
        """    :param message: Input text.\n"""
        """    :returns: Upper-cased text.\n"""
        '''    """\n'''
        """    return message.upper()\n""",
        encoding="utf-8",
    )
    manifest = build_manifest(targets=[source], artifact_root=tmp_path / "artifacts")
    server = McpServer(manifest)

    initialize = server.handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    )
    tools_list = server.handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    call = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "shout", "arguments": {"message": "mesh"}},
        }
    )

    assert initialize["result"]["serverInfo"]["name"] == "mcpwrap"
    assert tools_list["result"]["tools"][0]["name"] == "shout"
    assert call["result"]["content"][0]["text"] == "MESH"


def test_runtime_supports_async_jobs_tail_and_cancel(tmp_path: Path) -> None:
    """The runtime should support background subprocess jobs and persisted records."""

    script_path = tmp_path / "sleepy.py"
    script_path.write_text(
        "import sys\n"
        "import time\n\n"
        "delay = float(sys.argv[1])\n"
        "payload = sys.stdin.read().strip()\n"
        "print(f'start:{payload}', flush=True)\n"
        "time.sleep(delay)\n"
        "print(f'done:{payload}', flush=True)\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "mcpwrap.toml"
    config_path.write_text(
        f"""
[tool.mcpwrap]
artifact_root = "{(tmp_path / "artifacts").as_posix()}"

[[tool.mcpwrap.subprocess]]
name = "sleepy"
description = "Run slowly."
argv = ["{sys.executable}", "{script_path.as_posix()}", "{{delay}}"]
stdin_template = "{{message}}"
result_kind = "stdout_text"
timeout_seconds = 1.0

[tool.mcpwrap.subprocess.input_schema]
type = "object"
required = ["message", "delay"]

[tool.mcpwrap.subprocess.input_schema.properties.message]
type = "string"

[tool.mcpwrap.subprocess.input_schema.properties.delay]
type = "number"
""".strip(),
        encoding="utf-8",
    )

    server = McpServer(build_manifest(config_path=config_path))

    start_response = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "sleepy",
                "arguments": {"message": "mesh", "delay": 0.05},
                "_meta": {"mcpwrap/runMode": "async"},
            },
        }
    )
    job_id = start_response["result"]["_meta"]["mcpwrap/job"]["jobId"]
    for _ in range(50):
        job = server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "mcpwrap/jobs/get",
                "params": {"jobId": job_id},
            }
        )["result"]
        if job["status"] == "completed":
            break
        time.sleep(0.02)
    assert job["status"] == "completed"
    tail = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "mcpwrap/jobs/tail",
            "params": {"jobId": job_id, "stream": "stdout", "lines": 10},
        }
    )
    jobs_list = server.handle_request({"jsonrpc": "2.0", "id": 4, "method": "mcpwrap/jobs/list"})
    assert "done:mesh" in tail["result"]["lines"]
    assert any(item["jobId"] == job_id for item in jobs_list["result"]["jobs"])

    cancel_start = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "sleepy",
                "arguments": {"message": "cancel", "delay": 0.5},
                "_meta": {"mcpwrap/runMode": "async"},
            },
        }
    )
    cancel_job_id = cancel_start["result"]["_meta"]["mcpwrap/job"]["jobId"]
    server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "mcpwrap/jobs/cancel",
            "params": {"jobId": cancel_job_id},
        }
    )
    for _ in range(50):
        cancelled = server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "mcpwrap/jobs/get",
                "params": {"jobId": cancel_job_id},
            }
        )["result"]
        if cancelled["status"] == "cancelled":
            break
        time.sleep(0.02)
    assert cancelled["status"] == "cancelled"

"""Tests for execution and runtime edge paths."""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

from mcpwrap import ArgparseCommand, build_manifest, execute_tool, serve_stdio
from mcpwrap.execution import ToolExecutionResult, _extract_subprocess_result, _normalize_result
from mcpwrap.manifest import ArtifactPolicy, Manifest, SourceReference, ToolManifest


async def async_tool(job_name: str) -> str:
    """Run asynchronously.

    :param job_name: Job label.
    :returns: Upper-cased job label.
    """

    return job_name.upper()


def test_execution_covers_async_error_and_result_helpers(tmp_path: Path) -> None:
    """Async execution, error conversion, and result helpers should be exercised."""

    manifest = build_manifest(targets=[async_tool], artifact_root=tmp_path / "artifacts")
    result = execute_tool(manifest, "async_tool", {"job_name": "mesh"})
    assert result.content[0]["text"] == "MESH"

    broken_manifest = Manifest(
        tools=(
            ToolManifest(
                name="broken",
                description="Broken tool.",
                input_schema={"type": "object", "properties": {}},
                source=SourceReference(kind="broken", target="broken"),
                binding_kind="broken",
            ),
        ),
        artifact_policy=ArtifactPolicy(root_dir=tmp_path / "broken_artifacts"),
        runtime_bindings={"broken": object()},
    )
    broken_result = execute_tool(broken_manifest, "broken", {})
    assert broken_result.is_error is True
    assert "Unsupported binding type" in broken_result.content[0]["text"]

    helper = ToolExecutionResult(
        content=({"type": "text", "text": "ok"},),
        structured_content={"status": "ok"},
        is_error=True,
    )
    assert helper.to_mcp_result()["structuredContent"] == {"status": "ok"}
    assert helper.to_mcp_result()["isError"] is True

    plain = _normalize_result(object(), None)
    assert plain.content[0]["text"].startswith("<object object at")


def test_execution_supports_no_artifacts_stdio_and_argparse_false_flags(tmp_path: Path) -> None:
    """No-artifact subprocess runs should still honor stdin, env, cwd, and flags."""

    script_path = tmp_path / "stdin_cli.py"
    script_path.write_text(
        "import argparse\n"
        "import json\n"
        "import os\n"
        "import pathlib\n"
        "import sys\n\n"
        "parser = argparse.ArgumentParser()\n"
        "parser.add_argument('job_name')\n"
        "parser.add_argument('--cache', action='store_false')\n"
        "parser.add_argument('--samples', nargs='+')\n"
        "args = parser.parse_args()\n"
        "payload = (\n"
        "    pathlib.Path('stdin.txt').read_text(encoding='utf-8')\n"
        "    if pathlib.Path('stdin.txt').exists()\n"
        "    else sys.stdin.read()\n"
        ")\n"
        "print(\n"
        "    json.dumps(\n"
        "        {\n"
        "            'job_name': args.job_name,\n"
        "            'cache': args.cache,\n"
        "            'samples': args.samples,\n"
        "            'stdin': payload,\n"
        "            'cwd': pathlib.Path.cwd().name,\n"
        "        }\n"
        "    )\n"
        ")\n",
        encoding="utf-8",
    )
    parser = argparse.ArgumentParser(description="Drive the subprocess.")
    parser.add_argument("job_name")
    parser.add_argument("--cache", action="store_false")
    parser.add_argument("--samples", nargs="+")

    manifest = build_manifest(
        targets=[
            ArgparseCommand(
                name="drive_cli",
                parser=parser,
                command=(sys.executable, str(script_path)),
            )
        ],
        artifact_root=tmp_path / "artifacts",
    )
    result = execute_tool(
        manifest,
        "drive_cli",
        {"job_name": "mesh", "cache": False, "samples": ["1", "2"]},
    )
    parsed = json.loads(result.content[0]["text"])
    assert parsed["cache"] is False
    assert parsed["samples"] == ["1", "2"]

    env_script = tmp_path / "stdin_env.py"
    env_script.write_text(
        "import json\n"
        "import os\n"
        "import pathlib\n"
        "import sys\n\n"
        "pathlib.Path('stdin.txt').write_text(sys.stdin.read(), encoding='utf-8')\n"
        "print(json.dumps({'env': os.environ['MCPWRAP_FLAG'], 'cwd': pathlib.Path.cwd().name}))\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "mcpwrap.toml"
    config_path.write_text(
        f"""
[tool.mcpwrap]
artifact_mode = "none"

[[tool.mcpwrap.subprocess]]
name = "stdin_env"
description = "Read stdin and env."
argv = ["{sys.executable}", "{env_script.as_posix()}"]
stdin_template = "{{message}}"
cwd = "workspace"

[tool.mcpwrap.subprocess.input_schema]
type = "object"
required = ["message"]

[tool.mcpwrap.subprocess.input_schema.properties.message]
type = "string"

[tool.mcpwrap.subprocess.env]
MCPWRAP_FLAG = "enabled"
""".strip(),
        encoding="utf-8",
    )
    subprocess_manifest = build_manifest(config_path=config_path)
    subprocess_result = execute_tool(subprocess_manifest, "stdin_env", {"message": "payload"})
    assert subprocess_result.artifact_dir is None
    assert json.loads(subprocess_result.content[0]["text"]) == {
        "env": "enabled",
        "cwd": "workspace",
    }


def test_execution_supports_summary_artifacts_and_subprocess_timeouts(tmp_path: Path) -> None:
    """Summary retention and timeouts should behave distinctly from full retention."""

    sleepy_script = tmp_path / "sleepy.py"
    sleepy_script.write_text(
        "import pathlib\n"
        "import sys\n"
        "import time\n\n"
        "pathlib.Path('input.txt').write_text(sys.stdin.read(), encoding='utf-8')\n"
        "time.sleep(0.2)\n"
        "print('finished')\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "mcpwrap.toml"
    config_path.write_text(
        f"""
[tool.mcpwrap]
artifact_mode = "summary"
artifact_root = "{(tmp_path / "artifacts").as_posix()}"

[[tool.mcpwrap.subprocess]]
name = "sleepy"
description = "Sleep past the timeout."
argv = ["{sys.executable}", "{sleepy_script.as_posix()}"]
result_kind = "stdout_text"
stdin_template = "{{message}}"
timeout_seconds = 0.05

[tool.mcpwrap.subprocess.input_schema]
type = "object"
required = ["message"]

[tool.mcpwrap.subprocess.input_schema.properties.message]
type = "string"
""".strip(),
        encoding="utf-8",
    )

    manifest = build_manifest(config_path=config_path)
    result = execute_tool(manifest, "sleepy", {"message": "payload"})

    assert result.is_error is True
    assert "timed out" in result.content[0]["text"]
    assert result.artifact_dir is not None
    assert (result.artifact_dir / "invocation.json").exists()
    assert (result.artifact_dir / "execution.json").exists()
    assert (result.artifact_dir / "stdout.txt").exists()
    assert (result.artifact_dir / "stderr.txt").exists()
    assert not (result.artifact_dir / "input.txt").exists()
    assert result.meta is not None
    assert "mcpwrap/artifacts" in result.meta


def test_runtime_stdio_and_result_extractors_cover_edge_paths(tmp_path: Path) -> None:
    """The stdio loop and file result extractors should behave predictably."""

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "text.txt").write_text("hello", encoding="utf-8")
    (workspace / "data.json").write_text('{"status": "ok"}', encoding="utf-8")
    assert (
        _extract_subprocess_result(
            "",
            result_spec=type("Spec", (), {"kind": "file_text", "path": "text.txt"})(),
            workspace=workspace,
        )[1][0]["text"]
        == "hello"
    )
    assert _extract_subprocess_result(
        "",
        result_spec=type("Spec", (), {"kind": "file_json", "path": "data.json"})(),
        workspace=workspace,
    )[0] == {"status": "ok"}

    source = tmp_path / "tool.py"
    source.write_text(
        """def ping(message: str) -> str:\n"""
        '''    """Ping text.\n\n'''
        """    :param message: Input text.\n"""
        """    :returns: Same text.\n"""
        '''    """\n'''
        """    return message\n""",
        encoding="utf-8",
    )
    manifest = build_manifest(targets=[source])
    stdin = io.StringIO(
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        + "\n"
        + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        + "\n"
        + json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {}})
        + "\n"
    )
    stdout = io.StringIO()
    serve_stdio(manifest, stdin=stdin, stdout=stdout)
    responses = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert responses[0]["result"]["serverInfo"]["name"] == "mcpwrap"
    assert responses[1]["result"]["tools"][0]["name"] == "ping"
    assert responses[2]["error"]["code"] == -32000

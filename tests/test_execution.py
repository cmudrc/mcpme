"""Tests for deterministic tool execution."""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

from mcpcraft import build_manifest, execute_tool


def test_execute_python_tool_captures_artifacts(tmp_path: Path) -> None:
    """Python-backed tools should validate input and retain execution evidence."""

    source = tmp_path / "solver.py"
    source.write_text(
        "from dataclasses import dataclass\n\n"
        "@dataclass\n"
        "class SolverInput:\n"
        "    job_name: str\n"
        "    iterations: int\n\n"
        "def run_solver(config: SolverInput) -> dict[str, int | str]:\n"
        '    """Run the deterministic solver.\n\n'
        "    :param config: Structured solver configuration.\n"
        "    :returns: A run summary.\n"
        '    """\n'
        '    return {"job_name": config.job_name, "iterations": config.iterations}\n',
        encoding="utf-8",
    )

    manifest = build_manifest(targets=[source], artifact_root=tmp_path / "artifacts")
    result = execute_tool(
        manifest,
        "run_solver",
        {"config": {"job_name": "wing_box", "iterations": 5}},
    )

    assert result.is_error is False
    assert result.structured_content == {"job_name": "wing_box", "iterations": 5}
    assert result.artifact_dir is not None
    invocation = json.loads((result.artifact_dir / "invocation.json").read_text(encoding="utf-8"))
    assert invocation["tool"] == "run_solver"
    assert invocation["arguments"]["config"]["job_name"] == "wing_box"


def test_execute_subprocess_tool_from_config(tmp_path: Path) -> None:
    """Manifest-driven subprocess tools should support deterministic hydration."""

    script_path = tmp_path / "emit_json.py"
    script_path.write_text(
        "import json\n"
        "import pathlib\n"
        "import sys\n\n"
        "payload = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8'))\n"
        "print(json.dumps({'message': payload['message'], 'length': len(payload['message'])}))\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "mcpcraft.toml"
    config_path.write_text(
        f"""
[tool.mcpcraft]
artifact_mode = "full"
artifact_root = "{(tmp_path / "artifacts").as_posix()}"

[[tool.mcpcraft.subprocess]]
name = "emit_message"
description = "Emit a JSON summary from a rendered input file."
argv = ["{sys.executable}", "{script_path.as_posix()}", "input.json"]
result_kind = "stdout_json"

[tool.mcpcraft.subprocess.input_schema]
type = "object"
required = ["message"]

[tool.mcpcraft.subprocess.input_schema.properties.message]
type = "string"
description = "Message text."

[[tool.mcpcraft.subprocess.files]]
path = "input.json"
template = "{{{{\\"message\\": \\"{{message}}\\"}}}}"
""".strip(),
        encoding="utf-8",
    )

    manifest = build_manifest(config_path=config_path)
    result = execute_tool(manifest, "emit_message", {"message": "mesh"})

    assert result.is_error is False
    assert result.structured_content == {"message": "mesh", "length": 4}
    assert result.artifact_dir is not None
    assert (result.artifact_dir / "input.json").exists()


def test_execute_subprocess_supports_binary_results_and_retained_directories(
    tmp_path: Path,
) -> None:
    """Configured retained outputs should make directory artifacts inspectable."""

    script_path = tmp_path / "emit_artifacts.py"
    script_path.write_text(
        "import pathlib\n\n"
        "pathlib.Path('reports').mkdir(exist_ok=True)\n"
        "pathlib.Path('reports/summary.txt').write_text('ok', encoding='utf-8')\n"
        "pathlib.Path('report.bin').write_bytes(b'ABC')\n"
        "print('completed')\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "mcpcraft.toml"
    config_path.write_text(
        f"""
[tool.mcpcraft]
artifact_mode = "summary"
artifact_root = "{(tmp_path / "artifacts").as_posix()}"

[[tool.mcpcraft.subprocess]]
name = "emit_artifacts"
description = "Emit a binary file and retained report directory."
argv = ["{sys.executable}", "{script_path.as_posix()}"]
result_kind = "file_bytes"
result_path = "report.bin"
input_schema = {{ type = "object", properties = {{ }}, required = [] }}

[[tool.mcpcraft.subprocess.outputs]]
path = "reports"
kind = "directory"
when = "success"
""".strip(),
        encoding="utf-8",
    )

    manifest = build_manifest(config_path=config_path)
    result = execute_tool(manifest, "emit_artifacts", {})

    assert result.is_error is False
    assert result.structured_content == {
        "path": "report.bin",
        "contentBase64": base64.b64encode(b"ABC").decode("ascii"),
    }
    assert result.artifact_dir is not None
    assert (result.artifact_dir / "outputs" / "reports" / "summary.txt").exists()

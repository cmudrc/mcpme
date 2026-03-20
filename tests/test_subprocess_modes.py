"""Tests for subprocess result modes and error handling."""

from __future__ import annotations

import sys
from pathlib import Path

from mcpwrap import build_manifest, execute_tool


def test_subprocess_file_json_result_and_error_mode_are_supported(tmp_path: Path) -> None:
    """File-based results and failing subprocesses should normalize predictably."""

    writer = tmp_path / "writer.py"
    writer.write_text(
        "import json\n"
        "import pathlib\n\n"
        "pathlib.Path('result.json').write_text(json.dumps({'status': 'ok'}), encoding='utf-8')\n",
        encoding="utf-8",
    )
    failing = tmp_path / "failing.py"
    failing.write_text(
        "import sys\nsys.stderr.write('solver failed')\nraise SystemExit(2)\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "mcpwrap.toml"
    config_path.write_text(
        f"""
[tool.mcpwrap]
artifact_root = "{(tmp_path / "artifacts").as_posix()}"

[[tool.mcpwrap.subprocess]]
name = "write_result"
description = "Write a JSON result file."
argv = ["{sys.executable}", "{writer.as_posix()}"]
input_schema = {{ type = "object", properties = {{ }}, required = [] }}
result_kind = "file_json"
result_path = "result.json"

[[tool.mcpwrap.subprocess]]
name = "fail_result"
description = "Fail deterministically."
argv = ["{sys.executable}", "{failing.as_posix()}"]
input_schema = {{ type = "object", properties = {{ }}, required = [] }}
""".strip(),
        encoding="utf-8",
    )

    manifest = build_manifest(config_path=config_path)
    success = execute_tool(manifest, "write_result", {})
    failure = execute_tool(manifest, "fail_result", {})

    assert success.structured_content == {"status": "ok"}
    assert failure.is_error is True
    assert failure.content[0]["text"] == "solver failed"

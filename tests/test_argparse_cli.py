"""Tests for deterministic argparse command wrapping and the CLI entry point."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from mcpme import ArgparseCommand, build_manifest, execute_tool
from mcpme.cli import main


def test_argparse_command_builds_schema_and_executes(tmp_path: Path) -> None:
    """Registered argparse commands should expose schema and run deterministically."""

    script_path = tmp_path / "echo_cli.py"
    script_path.write_text(
        "import argparse\n"
        "import json\n\n"
        "parser = argparse.ArgumentParser()\n"
        "parser.add_argument('job_name')\n"
        "parser.add_argument('--scale', type=float, default=1.0)\n"
        "parser.add_argument('--verbose', action='store_true')\n"
        "args = parser.parse_args()\n"
        "print(\n"
        "    json.dumps(\n"
        "        {'job_name': args.job_name, 'scale': args.scale, 'verbose': args.verbose}\n"
        "    )\n"
        ")\n",
        encoding="utf-8",
    )
    parser = argparse.ArgumentParser(description="Run the deterministic CLI.")
    parser.add_argument("job_name", help="Job label.")
    parser.add_argument("--scale", type=float, default=1.0, help="Scale factor.")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose mode.")

    manifest = build_manifest(
        targets=[
            ArgparseCommand(
                name="run_cli",
                parser=parser,
                command=(sys.executable, str(script_path)),
            )
        ],
        artifact_root=tmp_path / "artifacts",
    )
    tool = manifest.get_tool("run_cli")
    result = execute_tool(
        manifest,
        "run_cli",
        {"job_name": "mesh", "scale": 2.5, "verbose": True},
    )

    assert tool.input_schema["properties"]["scale"]["type"] == "number"
    assert tool.input_schema["properties"]["verbose"]["type"] == "boolean"
    assert result.is_error is False
    assert json.loads(result.content[0]["text"]) == {
        "job_name": "mesh",
        "scale": 2.5,
        "verbose": True,
    }


def test_cli_manifest_and_inspect_commands_emit_deterministic_output(
    tmp_path: Path,
    capsys: object,
) -> None:
    """The CLI should expose inspectable manifest and summary output."""

    source = tmp_path / "mesh_tools.py"
    source.write_text(
        """def mesh_model(input_path: str) -> str:\n"""
        '''    """Generate a mesh.\n\n'''
        """    Args:\n"""
        """        input_path: CAD path.\n\n"""
        """    Returns:\n"""
        """        Mesh path.\n"""
        '''    """\n'''
        """    return input_path\n""",
        encoding="utf-8",
    )

    assert main(["manifest", str(source)]) == 0
    manifest_output = capsys.readouterr().out
    assert '"name": "mesh_model"' in manifest_output

    assert main(["inspect", str(source)]) == 0
    inspect_output = capsys.readouterr().out
    assert "mesh_model: Generate a mesh." in inspect_output

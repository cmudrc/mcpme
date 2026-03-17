"""Smoke tests for the checked-in runnable examples."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SUPPORT_REQUIREMENTS = {
    "argparse_cli_wrapper.py": (
        REPO_ROOT / "examples" / "support" / "argparse_cli_wrapper" / "beam_cli.py",
        REPO_ROOT
        / "examples"
        / "support"
        / "argparse_cli_wrapper"
        / "commands"
        / "run_beam_cli.sh",
    ),
    "command_scaffold.py": (
        REPO_ROOT / "examples" / "support" / "command_scaffold" / "beam_cli.py",
        REPO_ROOT / "examples" / "support" / "command_scaffold" / "commands" / "run_beam_cli.sh",
        REPO_ROOT
        / "examples"
        / "support"
        / "command_scaffold"
        / "commands"
        / "scaffold_command.sh",
    ),
    "openapi_scaffold.py": (
        REPO_ROOT / "examples" / "support" / "openapi_scaffold" / "solver_api.json",
        REPO_ROOT / "examples" / "support" / "openapi_scaffold" / "solver_api_server.py",
        REPO_ROOT
        / "examples"
        / "support"
        / "openapi_scaffold"
        / "commands"
        / "scaffold_openapi.sh",
    ),
    "package_scaffold.py": (
        REPO_ROOT
        / "examples"
        / "support"
        / "package_scaffold"
        / "workspace"
        / "demo_pkg"
        / "__init__.py",
        REPO_ROOT
        / "examples"
        / "support"
        / "package_scaffold"
        / "workspace"
        / "demo_pkg"
        / "core.py",
        REPO_ROOT
        / "examples"
        / "support"
        / "package_scaffold"
        / "commands"
        / "scaffold_package.sh",
    ),
    "subprocess_wrapper.py": (
        REPO_ROOT / "examples" / "support" / "subprocess_wrapper" / "mcpme.toml",
        REPO_ROOT / "examples" / "support" / "subprocess_wrapper" / "legacy_solver.py",
        REPO_ROOT
        / "examples"
        / "support"
        / "subprocess_wrapper"
        / "commands"
        / "run_legacy_solver.sh",
    ),
}


def _artifact_root_for(script_name: str) -> Path | None:
    """Return the artifact root for one example script when it has one."""
    if script_name in {"basic_usage.py", "runtime_server.py"}:
        return None
    return REPO_ROOT / "artifacts" / "examples" / Path(script_name).stem


@pytest.mark.parametrize(
    ("script_name", "expected_fragment"),
    [
        ("basic_usage.py", "summarize_mesh"),
        ("argparse_cli_wrapper.py", "cantilever"),
        ("command_scaffold.py", "run_beam_cli"),
        ("openapi_scaffold.py", "get_case"),
        ("package_scaffold.py", "create_counter_session"),
        ("subprocess_wrapper.py", "legacy_solver"),
        ("runtime_server.py", "inspect_case"),
    ],
)
def test_example_scripts_run_successfully(script_name: str, expected_fragment: str) -> None:
    """Each runnable example should execute and emit recognizable JSON output."""
    for required_path in SUPPORT_REQUIREMENTS.get(script_name, ()):
        assert required_path.exists(), f"Missing checked-in support input: {required_path}"
    artifact_root = _artifact_root_for(script_name)
    if artifact_root is not None:
        shutil.rmtree(artifact_root, ignore_errors=True)
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    completed = subprocess.run(
        [sys.executable, f"examples/{script_name}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    parsed = json.loads(completed.stdout)
    if isinstance(parsed, dict):
        assert parsed.get("isError") is not True
    rendered = json.dumps(parsed, sort_keys=True)
    assert expected_fragment in rendered

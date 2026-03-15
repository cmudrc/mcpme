"""Smoke tests for the checked-in runnable examples."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


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

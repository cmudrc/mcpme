"""Runnable example for one-shot package ingestion through scaffolded facades.

## Introduction

This example shows how to ingest an installed-style Python package that mixes
plain functions and stateful classes. The package is translated into a plain
Python facade first, then wrapped through the normal `mcpwrap` manifest flow.

## Preset Environment

The demo package and scaffold wrapper are checked in under
`examples/support/package_scaffold/`. That keeps the package source immediately
inspectable, while the generated facade remains a derived artifact under
`artifacts/examples/package_scaffold/`.

## Technical Implementation

- Keep the tiny package checked in under `examples/support/package_scaffold/`.
- Run the public scaffold CLI through a checked-in shell wrapper to generate a
  deterministic wrapper module.
- Build a manifest from the generated facade and execute both function and
  class-session tools through :func:`mcpwrap.execute_tool`.
- Print the scaffold report and the resulting tool outputs as JSON.

## Expected Results

Running this script prints a JSON object that includes the scaffold report, a
direct function result, and a session-based class interaction. The generated
facade remains on disk under `artifacts/examples/package_scaffold/`.

## References

- ``README.md``
- ``examples/support/package_scaffold/workspace/demo_pkg/__init__.py``
- ``examples/support/package_scaffold/workspace/demo_pkg/core.py``
- ``examples/support/package_scaffold/commands/scaffold_package.sh``
- ``docs/quickstart.rst``
- ``docs/specification.rst``
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from mcpwrap import build_manifest, execute_tool

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPO_ROOT / "examples" / "support" / "package_scaffold"
ARTIFACT_ROOT = REPO_ROOT / "artifacts" / "examples" / "package_scaffold"
WORKSPACE_ROOT = SOURCE_ROOT / "workspace"
SCAFFOLD_PATH = SOURCE_ROOT / "commands" / "scaffold_package.sh"


def _require_support_file(path: Path) -> Path:
    """Require one checked-in support file before running the example."""
    if not path.exists():
        raise FileNotFoundError(f"Missing checked-in example support file: {path}")
    return path


def _pythonpath_env(*paths: Path) -> dict[str, str]:
    """Build an environment that keeps `mcpwrap` importable for child processes."""
    env = dict(os.environ)
    extra_paths = [str(path.resolve()) for path in paths]
    current = env.get("PYTHONPATH")
    if current:
        extra_paths.append(current)
    env["PYTHONPATH"] = os.pathsep.join(extra_paths)
    env.setdefault("PYTHON_BIN", sys.executable)
    return env


def _scaffold_package(package_parent: Path, output_path: Path) -> dict[str, object]:
    """Run the public CLI package scaffold flow and return its JSON report."""
    completed = subprocess.run(
        ["sh", str(_require_support_file(SCAFFOLD_PATH).resolve()), str(output_path)],
        cwd=REPO_ROOT,
        env=_pythonpath_env(REPO_ROOT / "src", package_parent),
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(completed.stdout)


def run_example() -> dict[str, object]:
    """Ingest the example package, wrap it, and execute the generated tools."""
    package_root = WORKSPACE_ROOT / "demo_pkg"
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    output_path = ARTIFACT_ROOT / "generated_package_facade.py"

    package_parent = package_root.parent.resolve()
    if str(package_parent) not in sys.path:
        sys.path.insert(0, str(package_parent))

    report = _scaffold_package(package_parent, output_path)
    manifest = build_manifest(targets=[output_path], artifact_root=ARTIFACT_ROOT)
    solve_result = execute_tool(manifest, "solve", {"mesh_size": 4})
    create_result = execute_tool(manifest, "create_counter_session", {"start": 10})
    session_record = json.loads(create_result.content[0]["text"])
    increment_result = execute_tool(
        manifest,
        "counter_session_increment",
        {"session_id": session_record["session_id"], "amount": 5},
    )
    close_result = execute_tool(
        manifest,
        "close_counter_session",
        {"session_id": session_record["session_id"]},
    )
    return {
        "report": report,
        "solve": json.loads(solve_result.content[0]["text"]),
        "increment": json.loads(increment_result.content[0]["text"]),
        "close": json.loads(close_result.content[0]["text"]),
    }


def main() -> None:
    """Run the package scaffolding example and print JSON output."""
    print(json.dumps(run_example(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

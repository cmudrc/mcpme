"""Runnable example for one-shot package ingestion through scaffolded facades.

## Introduction

This example shows how to ingest an installed-style Python package that mixes
plain functions and stateful classes. The package is translated into a plain
Python facade first, then wrapped through the normal `mcpme` manifest flow.

## Technical Implementation

- Materialize a tiny package under `artifacts/examples/` so the example stays
  self-contained and inspectable.
- Run `python -m mcpme.cli scaffold-package` against that package to generate a
  deterministic wrapper module.
- Build a manifest from the generated facade and execute both function and
  class-session tools through :func:`mcpme.execute_tool`.
- Print the scaffold report and the resulting tool outputs as JSON.

## Expected Results

Running this script prints a JSON object that includes the scaffold report, a
direct function result, and a session-based class interaction. The generated
facade remains on disk under `artifacts/examples/package_scaffold/`.

## References

- ``README.md``
- ``docs/quickstart.rst``
- ``docs/specification.rst``
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from mcpme import build_manifest, execute_tool

SUPPORT_ROOT = Path("artifacts/examples/package_scaffold")


def _write_package(package_root: Path) -> None:
    """Write the tiny package ingested by the example."""
    package_root.mkdir(parents=True, exist_ok=True)
    (package_root / "__init__.py").write_text(
        '"""Tiny package used by the package scaffolding example."""\n'
        "from .core import CounterSession, solve\n\n"
        '__all__ = ["solve", "CounterSession"]\n',
        encoding="utf-8",
    )
    (package_root / "core.py").write_text(
        '"""Core package tools."""\n\n'
        "def solve(mesh_size: int = 2) -> int:\n"
        '    """Solve a deterministic case.\n\n'
        "    Args:\n"
        "        mesh_size: Mesh size.\n\n"
        "    Returns:\n"
        "        Scaled score.\n"
        '    """\n'
        "    return mesh_size * 3\n\n\n"
        "class CounterSession:\n"
        '    """Maintain a tiny mutable counter.\n\n'
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


def _pythonpath_env(*paths: Path) -> dict[str, str]:
    """Build an environment that keeps `mcpme` importable for child processes."""
    env = dict(os.environ)
    extra_paths = [str(path.resolve()) for path in paths]
    current = env.get("PYTHONPATH")
    if current:
        extra_paths.append(current)
    env["PYTHONPATH"] = os.pathsep.join(extra_paths)
    return env


def _scaffold_package(package_parent: Path, output_path: Path) -> dict[str, object]:
    """Run the public CLI package scaffold flow and return its JSON report."""
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "mcpme.cli",
            "scaffold-package",
            "demo_pkg",
            str(output_path),
        ],
        cwd=Path.cwd(),
        env=_pythonpath_env(Path("src"), package_parent),
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(completed.stdout)


def run_example() -> dict[str, object]:
    """Ingest the example package, wrap it, and execute the generated tools."""
    package_root = SUPPORT_ROOT / "workspace" / "demo_pkg"
    artifact_root = (SUPPORT_ROOT / "artifacts").resolve()
    output_path = SUPPORT_ROOT / "generated_package_facade.py"
    _write_package(package_root)

    package_parent = package_root.parent.resolve()
    if str(package_parent) not in sys.path:
        sys.path.insert(0, str(package_parent))

    report = _scaffold_package(package_parent, output_path)
    manifest = build_manifest(targets=[output_path], artifact_root=artifact_root)
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

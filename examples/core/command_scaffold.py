"""Runnable example for one-shot CLI ingestion through scaffolded facades.

## Introduction

This example shows how to ingest a standalone command-line tool whose public
interface is only exposed through `--help`. `mcpcraft` captures that help output,
turns it into a deterministic Python facade, and then wraps the facade like any
other source-backed tool.

## Preset Environment

The underlying CLI implementation and its command wrappers are checked in under
`examples/support/command_scaffold/`. That makes the help surface inspectable
before execution, while the generated facade still lands under
`artifacts/examples/core/command_scaffold/`.

## Technical Implementation

- Keep the tiny CLI and the scaffold command wrapper checked in under
  `examples/support/command_scaffold/`.
- Run the public scaffold CLI through the checked-in shell wrapper to generate
  a facade module under `artifacts/examples/core/command_scaffold/`.
- Build a manifest from the generated facade and execute it through
  :func:`mcpcraft.execute_tool`.
- Print the scaffold report and normalized subprocess result as JSON.

## Expected Results

Running this script prints a JSON object that includes the scaffold report and
the wrapped CLI output for a small beam case. The generated facade remains
available under `artifacts/examples/core/command_scaffold/`.

## References

- ``README.md``
- ``examples/support/command_scaffold/beam_cli.py``
- ``examples/support/command_scaffold/commands/run_beam_cli.sh``
- ``examples/support/command_scaffold/commands/scaffold_command.sh``
- ``docs/quickstart.rst``
- ``docs/specification.rst``
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from mcpcraft import build_manifest, execute_tool

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPO_ROOT / "examples" / "support" / "command_scaffold"
ARTIFACT_ROOT = REPO_ROOT / "artifacts" / "examples" / "core" / "command_scaffold"
SCAFFOLD_PATH = SOURCE_ROOT / "commands" / "scaffold_command.sh"


def _require_support_file(path: Path) -> Path:
    """Require one checked-in support file before running the example."""
    if not path.exists():
        raise FileNotFoundError(f"Missing checked-in example support file: {path}")
    return path


def _pythonpath_env() -> dict[str, str]:
    """Build an environment that keeps `mcpcraft` importable for child processes."""
    env = dict(os.environ)
    existing = env.get("PYTHONPATH")
    paths = [str((REPO_ROOT / "src").resolve())]
    if existing:
        paths.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(paths)
    env.setdefault("PYTHON_BIN", sys.executable)
    return env


def _scaffold_command(output_path: Path) -> dict[str, object]:
    """Run the public CLI command scaffold flow and return its JSON report."""
    completed = subprocess.run(
        ["sh", str(_require_support_file(SCAFFOLD_PATH).resolve()), str(output_path)],
        cwd=REPO_ROOT,
        env=_pythonpath_env(),
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(completed.stdout)


def run_example() -> dict[str, object]:
    """Ingest the example CLI, wrap it, and execute the generated tool."""
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    output_path = ARTIFACT_ROOT / "generated_cli_facade.py"
    report = _scaffold_command(output_path)
    manifest = build_manifest(targets=[output_path], artifact_root=ARTIFACT_ROOT)
    result = execute_tool(
        manifest,
        "run_beam_cli",
        {"job_name": "cantilever", "scale": 2.5, "verbose": True},
    )
    return {
        "report": report,
        "result": json.loads(result.content[0]["text"]),
    }


def main() -> None:
    """Run the command scaffolding example and print JSON output."""
    print(json.dumps(run_example(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

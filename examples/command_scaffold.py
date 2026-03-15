"""Runnable example for one-shot CLI ingestion through scaffolded facades.

## Introduction

This example shows how to ingest a standalone command-line tool whose public
interface is only exposed through `--help`. `mcpme` captures that help output,
turns it into a deterministic Python facade, and then wraps the facade like any
other source-backed tool.

## Technical Implementation

- Write a tiny `argparse`-based CLI under `artifacts/examples/`.
- Run `python -m mcpme.cli scaffold-command` to generate a wrapper module that
  exposes named MCP inputs for the command.
- Build a manifest from the generated facade and execute it through
  :func:`mcpme.execute_tool`.
- Print the scaffold report and normalized subprocess result as JSON.

## Expected Results

Running this script prints a JSON object that includes the scaffold report and
the wrapped CLI output for a small beam case. The generated facade remains
available under `artifacts/examples/command_scaffold/`.

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

SUPPORT_ROOT = Path("artifacts/examples/command_scaffold")


def _write_cli_script(path: Path) -> None:
    """Write the tiny CLI ingested by the example."""
    path.write_text(
        "import argparse\n"
        "import json\n\n"
        "parser = argparse.ArgumentParser(description='Deterministic beam CLI.')\n"
        "parser.add_argument('job_name', help='Job label.')\n"
        "parser.add_argument('--scale', type=float, default=1.0, help='Scale factor.')\n"
        "parser.add_argument('--verbose', action='store_true', help='Verbose mode.')\n"
        "args = parser.parse_args()\n"
        "print(\n"
        "    json.dumps(\n"
        "        {'job_name': args.job_name, 'scale': args.scale, 'verbose': args.verbose}\n"
        "    )\n"
        ")\n",
        encoding="utf-8",
    )


def _pythonpath_env() -> dict[str, str]:
    """Build an environment that keeps `mcpme` importable for child processes."""
    env = dict(os.environ)
    existing = env.get("PYTHONPATH")
    paths = [str(Path("src").resolve())]
    if existing:
        paths.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(paths)
    return env


def _scaffold_command(script_path: Path, output_path: Path) -> dict[str, object]:
    """Run the public CLI command scaffold flow and return its JSON report."""
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "mcpme.cli",
            "scaffold-command",
            str(output_path),
            "--name",
            "run_beam_cli",
            "--",
            sys.executable,
            str(script_path.resolve()),
        ],
        cwd=Path.cwd(),
        env=_pythonpath_env(),
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(completed.stdout)


def run_example() -> dict[str, object]:
    """Ingest the example CLI, wrap it, and execute the generated tool."""
    SUPPORT_ROOT.mkdir(parents=True, exist_ok=True)
    script_path = SUPPORT_ROOT / "beam_cli.py"
    output_path = SUPPORT_ROOT / "generated_cli_facade.py"
    artifact_root = (SUPPORT_ROOT / "artifacts").resolve()
    _write_cli_script(script_path)
    report = _scaffold_command(script_path, output_path)
    manifest = build_manifest(targets=[output_path], artifact_root=artifact_root)
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

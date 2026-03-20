"""Runnable example for deterministic ``argparse`` CLI wrapping.

## Introduction

This example wraps a small command-line engineering helper that already exposes
its interface through `argparse`. That is a strong deterministic source of
truth, so `mcpcraft` can build a tool schema without resorting to heuristics.

## Preset Environment

The inspectable CLI implementation lives under
`examples/support/argparse_cli_wrapper/beam_cli.py`, and the visible command
surface lives under
`examples/support/argparse_cli_wrapper/commands/run_beam_cli.sh`. Running the
example only produces derived outputs under `artifacts/examples/core/argparse_cli_wrapper/`.

## Technical Implementation

- Keep the wrapped CLI and its shell launcher checked in under
  `examples/support/`.
- Register its parser and command prefix with :class:`mcpcraft.ArgparseCommand`.
- Build a manifest from that registration and execute it through
  :func:`mcpcraft.execute_tool`.
- Print the normalized MCP result so you can see the transport shape clients
  would receive.

## Expected Results

Running this script prints a JSON result describing a beam case. The underlying
CLI receives normal command-line arguments, while `mcpcraft` handles validation,
argument rendering, and result normalization.

## References

- ``README.md``
- ``examples/support/argparse_cli_wrapper/beam_cli.py``
- ``examples/support/argparse_cli_wrapper/commands/run_beam_cli.sh``
- ``docs/quickstart.rst``
- ``docs/api.rst``
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from mcpcraft import ArgparseCommand, ToolExecutionResult, build_manifest, execute_tool

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPO_ROOT / "examples" / "support" / "argparse_cli_wrapper"
ARTIFACT_ROOT = REPO_ROOT / "artifacts" / "examples" / "core" / "argparse_cli_wrapper"
COMMAND_PATH = SOURCE_ROOT / "commands" / "run_beam_cli.sh"


def _require_support_file(path: Path) -> Path:
    """Require one checked-in support file before running the example."""
    if not path.exists():
        raise FileNotFoundError(f"Missing checked-in example support file: {path}")
    return path


def _build_parser() -> argparse.ArgumentParser:
    """Build the parser surface mirrored by the wrapped CLI."""
    parser = argparse.ArgumentParser(description="Beam post-processor.")
    parser.add_argument("case_name", help="Named beam case to post-process.")
    parser.add_argument("--scale", type=float, default=1.0, help="Stress scale factor.")
    parser.add_argument("--export-vtk", action="store_true", help="Emit a VTK-ready flag.")
    return parser


def run_example() -> ToolExecutionResult:
    """Execute the wrapped argparse CLI through the public API."""
    os.environ.setdefault("PYTHON_BIN", sys.executable)
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest(
        targets=[
            ArgparseCommand(
                name="beam_cli",
                parser=_build_parser(),
                command=("sh", str(_require_support_file(COMMAND_PATH).resolve())),
                description="Run a beam post-processing CLI.",
            )
        ],
        artifact_root=ARTIFACT_ROOT,
    )
    return execute_tool(
        manifest,
        "beam_cli",
        {"case_name": "cantilever", "scale": 1.5, "export_vtk": True},
    )


def main() -> None:
    """Run the argparse wrapper example and print the normalized result."""
    result = run_example()
    print(json.dumps(result.to_mcp_result(), indent=2, sort_keys=True))
    if result.is_error:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

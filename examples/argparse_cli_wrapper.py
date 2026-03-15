"""Runnable example for deterministic ``argparse`` CLI wrapping.

## Introduction

This example wraps a small command-line engineering helper that already exposes
its interface through `argparse`. That is a strong deterministic source of
truth, so `mcpme` can build a tool schema without resorting to heuristics.

## Technical Implementation

- Materialize a tiny CLI script under `artifacts/examples/` so the example stays
  self-contained and runnable from the repository root.
- Register its parser and command prefix with :class:`mcpme.ArgparseCommand`.
- Build a manifest from that registration and execute it through
  :func:`mcpme.execute_tool`.
- Print the normalized MCP result so you can see the transport shape clients
  would receive.

## Expected Results

Running this script prints a JSON result describing a beam case. The underlying
CLI receives normal command-line arguments, while `mcpme` handles validation,
argument rendering, and result normalization.

## References

- ``README.md``
- ``docs/quickstart.rst``
- ``docs/api.rst``
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from mcpme import ArgparseCommand, ToolExecutionResult, build_manifest, execute_tool

SUPPORT_ROOT = Path("artifacts/examples/argparse_cli_wrapper")


def _write_cli_script(path: Path) -> None:
    """Write the small deterministic CLI used by the example."""
    path.write_text(
        "import argparse\n"
        "import json\n\n"
        "parser = argparse.ArgumentParser(description='Beam post-processor.')\n"
        "parser.add_argument('case_name')\n"
        "parser.add_argument('--scale', type=float, default=1.0)\n"
        "parser.add_argument('--export-vtk', action='store_true')\n"
        "args = parser.parse_args()\n"
        "print(json.dumps({\n"
        "    'case_name': args.case_name,\n"
        "    'scale': args.scale,\n"
        "    'export_vtk': args.export_vtk,\n"
        "    'stress_limit': round(125.0 * args.scale, 3),\n"
        "}, sort_keys=True))\n",
        encoding="utf-8",
    )


def _build_parser() -> argparse.ArgumentParser:
    """Build the parser surface mirrored by the wrapped CLI."""
    parser = argparse.ArgumentParser(description="Beam post-processor.")
    parser.add_argument("case_name", help="Named beam case to post-process.")
    parser.add_argument("--scale", type=float, default=1.0, help="Stress scale factor.")
    parser.add_argument("--export-vtk", action="store_true", help="Emit a VTK-ready flag.")
    return parser


def run_example() -> ToolExecutionResult:
    """Execute the wrapped argparse CLI through the public API."""
    SUPPORT_ROOT.mkdir(parents=True, exist_ok=True)
    script_path = SUPPORT_ROOT / "beam_cli.py"
    artifact_root = (SUPPORT_ROOT / "artifacts").resolve()
    _write_cli_script(script_path)
    manifest = build_manifest(
        targets=[
            ArgparseCommand(
                name="beam_cli",
                parser=_build_parser(),
                command=(sys.executable, str(script_path.resolve())),
                description="Run a beam post-processing CLI.",
            )
        ],
        artifact_root=artifact_root,
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

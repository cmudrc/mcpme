"""Runnable example for a manifest-driven legacy-style subprocess wrapper.

## Introduction

This example wraps a legacy-style batch solver that communicates through input
and output files. That is a common engineering pattern, and it is exactly where
deterministic manifest-driven subprocess wrapping is more useful than trying to
rewrite the solver.

## Preset Environment

The checked-in subprocess contract lives under
`examples/support/subprocess_wrapper/`: the stand-in solver, the manifest TOML,
and the shell launcher are all inspectable before execution. Running the
example only creates derived execution artifacts under
`artifacts/examples/subprocess_wrapper/`.

## Technical Implementation

- Keep the stand-in solver, `mcpme.toml`, and shell launcher checked in under
  `examples/support/subprocess_wrapper/`.
- Build a manifest from that config and call the wrapped tool with
  :func:`mcpme.execute_tool`.
- Print the MCP result so the structured content and retained artifact metadata
  are visible.

## Expected Results

Running this script prints a structured result with a computed lift estimate and
includes `_meta` artifact details. The retained report file remains available
under `artifacts/examples/subprocess_wrapper/`.

## References

- ``README.md``
- ``examples/support/subprocess_wrapper/mcpme.toml``
- ``examples/support/subprocess_wrapper/legacy_solver.py``
- ``examples/support/subprocess_wrapper/commands/run_legacy_solver.sh``
- ``docs/specification.rst``
- ``docs/quickstart.rst``
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from mcpme import ToolExecutionResult, build_manifest, execute_tool

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPO_ROOT / "examples" / "support" / "subprocess_wrapper"
ARTIFACT_ROOT = REPO_ROOT / "artifacts" / "examples" / "subprocess_wrapper"
CONFIG_PATH = SOURCE_ROOT / "mcpme.toml"


def run_example() -> ToolExecutionResult:
    """Execute the manifest-driven subprocess example."""
    os.environ.setdefault("PYTHON_BIN", sys.executable)
    os.environ.setdefault("MCPME_EXAMPLE_SOURCE_ROOT", str(SOURCE_ROOT.resolve()))
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest(config_path=CONFIG_PATH, artifact_root=ARTIFACT_ROOT)
    return execute_tool(
        manifest,
        "legacy_solver",
        {"case_name": "wing_box", "velocity": 82.0, "area": 1.6},
    )


def main() -> None:
    """Run the subprocess wrapper example and print the normalized result."""
    result = run_example()
    print(json.dumps(result.to_mcp_result(), indent=2, sort_keys=True))
    if result.is_error:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

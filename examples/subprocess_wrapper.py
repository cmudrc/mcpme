"""Runnable example for a manifest-driven legacy-style subprocess wrapper.

## Introduction

This example wraps a legacy-style batch solver that communicates through input
and output files. That is a common engineering pattern, and it is exactly where
deterministic manifest-driven subprocess wrapping is more useful than trying to
rewrite the solver.

## Technical Implementation

- Write a tiny stand-in solver under `artifacts/examples/` that reads an input
  deck and writes both a JSON result and a report file.
- Materialize a local `mcpme.toml` sidecar that describes the subprocess
  command, input schema, rendered files, and retained outputs.
- Build a manifest from that config and call the wrapped tool with
  :func:`mcpme.execute_tool`.
- Print the MCP result so the structured content and retained artifact metadata
  are visible.

## Expected Results

Running this script prints a structured result with a computed lift estimate and
includes `_meta` artifact details. The retained report file remains available
under `artifacts/examples/subprocess_wrapper/artifacts/`.

## References

- ``README.md``
- ``docs/specification.rst``
- ``docs/quickstart.rst``
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from mcpme import ToolExecutionResult, build_manifest, execute_tool

SUPPORT_ROOT = Path("artifacts/examples/subprocess_wrapper")


def _write_solver_script(path: Path) -> None:
    """Write the deterministic stand-in solver used by the example."""
    path.write_text(
        "import json\n"
        "from pathlib import Path\n\n"
        "deck = json.loads(Path('deck.json').read_text(encoding='utf-8'))\n"
        "lift = round(deck['velocity'] * deck['area'] * 0.5, 3)\n"
        "Path('result.json').write_text(\n"
        "    json.dumps({'case_name': deck['case_name'], 'lift': lift}, sort_keys=True),\n"
        "    encoding='utf-8',\n"
        ")\n"
        "reports = Path('reports')\n"
        "reports.mkdir(exist_ok=True)\n"
        "Path(reports / 'summary.txt').write_text(\n"
        "    f\"case={deck['case_name']} lift={lift}\\n\",\n"
        "    encoding='utf-8',\n"
        ")\n"
        "print('solver finished')\n",
        encoding="utf-8",
    )


def _write_config(path: Path, solver_script: Path, artifact_root: Path) -> None:
    """Write the subprocess manifest configuration used by the example."""
    path.write_text(
        (
            "[tool.mcpme]\n"
            f'artifact_root = "{artifact_root.as_posix()}"\n'
            'artifact_mode = "summary"\n\n'
            "[[tool.mcpme.subprocess]]\n"
            'name = "legacy_solver"\n'
            'description = "Run a deterministic file-driven legacy solver."\n'
            f'argv = ["{sys.executable}", "{solver_script.as_posix()}"]\n'
            'result_kind = "file_json"\n'
            'result_path = "result.json"\n\n'
            "[tool.mcpme.subprocess.input_schema]\n"
            'type = "object"\n'
            'required = ["case_name", "velocity", "area"]\n\n'
            "[tool.mcpme.subprocess.input_schema.properties.case_name]\n"
            'type = "string"\n\n'
            "[tool.mcpme.subprocess.input_schema.properties.velocity]\n"
            'type = "number"\n\n'
            "[tool.mcpme.subprocess.input_schema.properties.area]\n"
            'type = "number"\n\n'
            "[[tool.mcpme.subprocess.files]]\n"
            'path = "deck.json"\n'
            'template = "{{\\"case_name\\": \\"{case_name}\\", '
            '\\"velocity\\": {velocity}, \\"area\\": {area}}}"\n\n'
            "[[tool.mcpme.subprocess.outputs]]\n"
            'path = "reports"\n'
            'kind = "directory"\n'
            'when = "success"\n'
        ),
        encoding="utf-8",
    )


def run_example() -> ToolExecutionResult:
    """Execute the manifest-driven subprocess example."""
    SUPPORT_ROOT.mkdir(parents=True, exist_ok=True)
    solver_script = SUPPORT_ROOT / "legacy_solver.py"
    config_path = SUPPORT_ROOT / "mcpme.toml"
    artifact_root = (SUPPORT_ROOT / "artifacts").resolve()
    _write_solver_script(solver_script)
    _write_config(config_path, solver_script.resolve(), artifact_root)
    manifest = build_manifest(config_path=config_path)
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

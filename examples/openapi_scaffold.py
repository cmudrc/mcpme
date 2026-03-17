"""Runnable example for one-shot OpenAPI ingestion through scaffolded facades.

## Introduction

This example shows how to ingest an OpenAPI specification without adding any
runtime AI layer. `mcpme` turns the spec into a plain Python HTTP facade, then
wraps the generated functions through its normal deterministic discovery path.

## Preset Environment

The OpenAPI document, local test server, and scaffold wrapper are checked in
under `examples/support/openapi_scaffold/`. That makes the source API surface
inspectable before running the example, while the generated facade remains a
derived artifact under `artifacts/examples/openapi_scaffold/`.

## Technical Implementation

- Keep the OpenAPI document and local server checked in under
  `examples/support/openapi_scaffold/`.
- Run the public scaffold CLI through a checked-in shell wrapper to generate a
  Python facade for the API operations.
- Build a manifest from the generated facade and execute the resulting tools
  through :func:`mcpme.execute_tool`.
- Print the scaffold report and the normalized HTTP responses as JSON.

## Expected Results

Running this script prints a JSON object that includes the scaffold report plus
two wrapped HTTP calls: one `GET` operation and one `POST` operation. The
generated facade remains available under `artifacts/examples/openapi_scaffold/`.

## References

- ``README.md``
- ``examples/support/openapi_scaffold/solver_api.json``
- ``examples/support/openapi_scaffold/solver_api_server.py``
- ``examples/support/openapi_scaffold/commands/scaffold_openapi.sh``
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
from support.openapi_scaffold.solver_api_server import solver_api_server

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPO_ROOT / "examples" / "support" / "openapi_scaffold"
ARTIFACT_ROOT = REPO_ROOT / "artifacts" / "examples" / "openapi_scaffold"
SCAFFOLD_PATH = SOURCE_ROOT / "commands" / "scaffold_openapi.sh"


def _require_support_file(path: Path) -> Path:
    """Require one checked-in support file before running the example."""
    if not path.exists():
        raise FileNotFoundError(f"Missing checked-in example support file: {path}")
    return path


def _pythonpath_env() -> dict[str, str]:
    """Build an environment that keeps `mcpme` importable for child processes."""
    env = dict(os.environ)
    existing = env.get("PYTHONPATH")
    paths = [str((REPO_ROOT / "src").resolve())]
    if existing:
        paths.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(paths)
    env.setdefault("PYTHON_BIN", sys.executable)
    return env


def _scaffold_openapi(output_path: Path) -> dict[str, object]:
    """Run the public OpenAPI scaffold flow and return its JSON report."""
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
    """Ingest the example OpenAPI spec and execute the generated wrappers."""
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    output_path = ARTIFACT_ROOT / "generated_openapi_facade.py"
    report = _scaffold_openapi(output_path)
    manifest = build_manifest(targets=[output_path], artifact_root=ARTIFACT_ROOT)
    with solver_api_server() as base_url:
        get_result = execute_tool(
            manifest,
            "get_case",
            {
                "case_id": "wing_box",
                "verbose": True,
                "x_mode": "detail",
                "base_url": base_url,
            },
        )
        create_result = execute_tool(
            manifest,
            "create_case",
            {"body": {"name": "cantilever"}, "base_url": base_url},
        )
    return {
        "report": report,
        "get_case": json.loads(get_result.content[0]["text"]),
        "create_case": json.loads(create_result.content[0]["text"]),
    }


def main() -> None:
    """Run the OpenAPI scaffolding example and print JSON output."""
    print(json.dumps(run_example(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

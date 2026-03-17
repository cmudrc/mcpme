"""Case study for one-shot scaffolding of OpenMDAO pyCycle's `MPCycle`.

## Introduction

This case study shows how `mcpme` can carve a useful session-oriented wrapper
out of a real engineering Python package without promoting package-specific
logic into the public API. It focuses on the object lifecycle around
`pycycle.api.MPCycle` rather than a full thermodynamic solve.

## Preset Environment

The case-study-specific scaffold command is checked in under
`case_studies/support/pycycle_mpcycle/commands/`, so the exact public CLI
invocation stays inspectable. Generated facades and runtime artifacts are
written under `artifacts/case_studies/pycycle_mpcycle/`.

## Technical Implementation

- Require `import pycycle.api` to succeed so the case study only runs against
  the engineering `om-pycycle` package.
- Run the public scaffold CLI through a checked-in shell wrapper with a narrow
  symbol include for `MPCycle`.
- Build a manifest from the generated facade through the top-level public API.
- Execute a minimal lifecycle: create the session, call
  `pyc_add_cycle_param`, and close the session.

## Expected Results

When the engineering pyCycle package is available, running this script prints a
JSON object with `status="passed"`, the scaffold report, and the session
lifecycle outputs. On machines without `pycycle.api`, the script prints
`status="skipped_unavailable"` with a stable reason and still exits
successfully.

## Availability

This case study requires the OpenMDAO pyCycle distribution, installed from the
`om-pycycle` package while still importing as `pycycle`. If `pycycle.api`
cannot be imported, the script skips cleanly.

## References

- ``README.md``
- ``case_studies/README.md``
- ``case_studies/support/pycycle_mpcycle/commands/scaffold_pycycle_mpcycle.sh``
- ``docs/quickstart.rst``
- ``docs/specification.rst``
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

from mcpme import build_manifest, execute_tool

CASE_STUDY_ID = "pycycle_mpcycle"
REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPO_ROOT / "case_studies" / "support" / "pycycle_mpcycle"
ARTIFACT_ROOT = REPO_ROOT / "artifacts" / "case_studies" / "pycycle_mpcycle"
SCAFFOLD_PATH = SOURCE_ROOT / "commands" / "scaffold_pycycle_mpcycle.sh"


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


def _skip(reason: str) -> dict[str, object]:
    """Build a stable skipped case-study payload."""
    return {
        "case_study": CASE_STUDY_ID,
        "reason": reason,
        "status": "skipped_unavailable",
    }


def _require_support_file(path: Path) -> Path:
    """Require one checked-in support file before running the case study."""
    if not path.exists():
        raise FileNotFoundError(f"Missing checked-in case-study support file: {path}")
    return path


def _scaffold_package(output_path: Path) -> dict[str, object]:
    """Run the public package scaffold flow for `pycycle.api`."""
    completed = subprocess.run(
        ["sh", str(_require_support_file(SCAFFOLD_PATH).resolve()), str(output_path)],
        cwd=REPO_ROOT,
        env=_pythonpath_env(),
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(completed.stdout)


def _tool_name(
    report: dict[str, object],
    *,
    name_prefix: str,
    source_suffix: str,
) -> str:
    """Look up one generated tool name from the scaffold report."""
    generated = report.get("generatedTools")
    if not isinstance(generated, list):
        raise ValueError("Scaffold report is missing generatedTools.")
    for entry in generated:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        source = entry.get("source")
        if (
            isinstance(name, str)
            and isinstance(source, str)
            and name.startswith(name_prefix)
            and source.endswith(source_suffix)
        ):
            return name
    raise ValueError(
        f"Unable to find generated tool with prefix {name_prefix!r} and source suffix "
        f"{source_suffix!r}."
    )


def run_case_study() -> dict[str, object]:
    """Execute the pyCycle case study and return the stable JSON payload."""
    try:
        importlib.import_module("pycycle.api")
    except Exception as exc:
        return _skip(f"Import probe failed for 'pycycle.api': {exc}")

    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    output_path = ARTIFACT_ROOT / "generated_pycycle_facade.py"
    report = _scaffold_package(output_path)
    manifest = build_manifest(targets=[output_path], artifact_root=ARTIFACT_ROOT)

    create_name = _tool_name(report, name_prefix="create_", source_suffix=".MPCycle")
    param_name = _tool_name(
        report,
        name_prefix="mpcycle_",
        source_suffix=".MPCycle.pyc_add_cycle_param",
    )
    close_name = _tool_name(report, name_prefix="close_", source_suffix=".MPCycle")

    create_result = execute_tool(manifest, create_name, {})
    session_record = json.loads(create_result.content[0]["text"])
    session_id = session_record["session_id"]

    add_param_result = execute_tool(
        manifest,
        param_name,
        {"session_id": session_id, "name": "FAR", "val": 0.02},
    )
    close_result = execute_tool(manifest, close_name, {"session_id": session_id})
    close_record = json.loads(close_result.content[0]["text"])
    if close_record.get("success") is not True:
        raise ValueError("Expected the generated close wrapper to report success.")

    return {
        "case_study": CASE_STUDY_ID,
        "report": report,
        "result": {
            "close": close_record,
            "create": session_record,
            "manifest_tool_names": list(manifest.tool_names),
            "pyc_add_cycle_param": json.loads(add_param_result.content[0]["text"]),
        },
        "status": "passed",
    }


def main() -> None:
    """Run the pyCycle case study and print the JSON payload."""
    print(json.dumps(run_case_study(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

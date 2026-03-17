"""Case study for one-shot scaffolding of the SU2 CFD command-line surface.

## Introduction

This case study documents how `mcpme` can wrap a heavyweight engineering CLI
without baking SU2-specific logic into the library itself. The workflow stays
honest about optional availability: if `SU2_CFD` is not installed, the case
study reports `skipped_unavailable` instead of pretending to be runnable.

## Preset Environment

The inspectable command surface for this case study lives under
`case_studies/support/su2_cli/commands/`. The checked-in wrappers show exactly
how `SU2_CFD -h` is probed and scaffolded, while generated facades and runtime
artifacts are written under `artifacts/case_studies/su2_cli/`.

## Technical Implementation

- Probe for `SU2_CFD` on `PATH` before attempting any scaffolding work.
- Run the public scaffold CLI through a checked-in shell wrapper with `-h` as
  the help probe path.
- Build a manifest from the generated facade through the top-level public API.
- Execute the generated wrapper with `extra_argv=["-h"]` and retain the
  normalized subprocess payload as JSON.

## Expected Results

When SU2 is available, running this script prints a JSON object with
`status="passed"`, the scaffold report, and the wrapped help-path result. On
machines without SU2 installed, the script prints `status="skipped_unavailable"`
with a stable reason and still exits successfully.

## Availability

This case study requires the `SU2_CFD` executable to be available on `PATH`.
The repository does not install SU2 automatically, and the case study is
expected to skip cleanly on machines without that runtime.

## References

- ``README.md``
- ``case_studies/README.md``
- ``case_studies/support/su2_cli/commands/su2_cfd.sh``
- ``case_studies/support/su2_cli/commands/scaffold_su2_cli.sh``
- ``docs/quickstart.rst``
- ``docs/specification.rst``
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from mcpme import build_manifest, execute_tool

CASE_STUDY_ID = "su2_cli"
REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPO_ROOT / "case_studies" / "support" / "su2_cli"
ARTIFACT_ROOT = REPO_ROOT / "artifacts" / "case_studies" / "su2_cli"
SCAFFOLD_PATH = SOURCE_ROOT / "commands" / "scaffold_su2_cli.sh"


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


def _scaffold_command(output_path: Path) -> dict[str, object]:
    """Run the public command scaffold flow for `SU2_CFD`."""
    completed = subprocess.run(
        ["sh", str(_require_support_file(SCAFFOLD_PATH).resolve()), str(output_path)],
        cwd=REPO_ROOT,
        env=_pythonpath_env(),
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(completed.stdout)


def run_case_study() -> dict[str, object]:
    """Execute the SU2 command case study and return the stable JSON payload."""
    if shutil.which("SU2_CFD") is None:
        return _skip("Availability probe command is unavailable on PATH: 'SU2_CFD'")

    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    output_path = ARTIFACT_ROOT / "generated_su2_facade.py"
    report = _scaffold_command(output_path)
    manifest = build_manifest(targets=[output_path], artifact_root=ARTIFACT_ROOT)
    result = execute_tool(manifest, "run_su2_cfd", {"extra_argv": ["-h"]})
    rendered_result = result.to_mcp_result()
    rendered_text = json.dumps(rendered_result, sort_keys=True)
    if "SU2_CFD" not in rendered_text:
        raise ValueError("Expected the wrapped SU2 help output to mention 'SU2_CFD'.")
    return {
        "case_study": CASE_STUDY_ID,
        "report": report,
        "result": rendered_result,
        "status": "passed",
    }


def main() -> None:
    """Run the SU2 case study and print the JSON payload."""
    print(json.dumps(run_case_study(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

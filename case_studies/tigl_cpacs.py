"""Case study for one-shot scaffolding around a tiny TiGL/TiXI CPACS helper.

## Introduction

This case study tackles a more awkward upstream than the small core examples:
TiGL workflows often revolve around native handles and CPACS files. Instead of
teaching `mcpme` about those details directly, the case study keeps a tiny
helper package checked in with a JSON-friendly function, scaffolds that package
through the public CLI, and then wraps the generated facade through the normal
public manifest flow.

## Preset Environment

The helper package and scaffold wrapper are checked in under
`case_studies/support/tigl_cpacs/`, and the real D150 CPACS XML fixture is
checked in under `case_studies/fixtures/`. Running the case study only creates
derived outputs under `artifacts/case_studies/tigl_cpacs/`.

## Technical Implementation

- Require the real `tigl3` and `tixi3` Python bindings before doing any work.
- Keep a tiny installed-style helper package checked in under
  `case_studies/support/tigl_cpacs/`.
- Use the public package scaffold flow through a checked-in shell wrapper to
  generate a facade for that helper package.
- Build a manifest from the generated facade and execute a CPACS summary tool
  against a checked-in TiGL fixture.

## Expected Results

When the TiGL and TiXI Python bindings are available, running this script
prints a JSON object with `status="passed"`, the scaffold report, and a
JSON-friendly CPACS summary produced through the real runtimes. On machines
without those bindings, the script prints `status="skipped_unavailable"` with a
stable reason and still exits successfully.

## Availability

This case study requires the real `tigl3` and `tixi3` Python bindings, which
are typically installed outside the base Python toolchain. The repository does
not install them automatically, so the case study is expected to skip cleanly
on many machines.

## References

- ``README.md``
- ``case_studies/README.md``
- ``case_studies/support/tigl_cpacs/tigl_support/__init__.py``
- ``case_studies/support/tigl_cpacs/tigl_support/core.py``
- ``case_studies/support/tigl_cpacs/commands/scaffold_tigl_cpacs.sh``
- ``case_studies/fixtures/CPACS_30_D150.xml``
- ``docs/quickstart.rst``
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

from mcpme import build_manifest, execute_tool

CASE_STUDY_ID = "tigl_cpacs"
REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPO_ROOT / "case_studies" / "support" / "tigl_cpacs"
ARTIFACT_ROOT = REPO_ROOT / "artifacts" / "case_studies" / "tigl_cpacs"
SCAFFOLD_PATH = SOURCE_ROOT / "commands" / "scaffold_tigl_cpacs.sh"
FIXTURE_PATH = REPO_ROOT / "case_studies" / "fixtures" / "CPACS_30_D150.xml"


def _pythonpath_env(*paths: Path) -> dict[str, str]:
    """Build an environment that keeps `mcpme` and helper packages importable."""
    env = dict(os.environ)
    extra_paths = [str(path.resolve()) for path in paths]
    current = env.get("PYTHONPATH")
    if current:
        extra_paths.append(current)
    env["PYTHONPATH"] = os.pathsep.join(extra_paths)
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


def _scaffold_package(package_parent: Path, output_path: Path) -> dict[str, object]:
    """Run the public package scaffold flow for the helper package."""
    completed = subprocess.run(
        ["sh", str(_require_support_file(SCAFFOLD_PATH).resolve()), str(output_path)],
        cwd=REPO_ROOT,
        env=_pythonpath_env(REPO_ROOT / "src", package_parent),
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(completed.stdout)


def run_case_study() -> dict[str, object]:
    """Execute the TiGL case study and return the stable JSON payload."""
    try:
        importlib.import_module("tigl3.tigl3wrapper")
        importlib.import_module("tixi3.tixi3wrapper")
    except Exception as exc:
        return _skip(f"Import probe failed for TiGL/TiXI bindings: {exc}")

    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    package_root = SOURCE_ROOT / "tigl_support"
    output_path = ARTIFACT_ROOT / "generated_tigl_facade.py"

    package_parent = package_root.parent.resolve()
    if str(package_parent) not in sys.path:
        sys.path.insert(0, str(package_parent))

    report = _scaffold_package(package_parent, output_path)
    manifest = build_manifest(targets=[output_path], artifact_root=ARTIFACT_ROOT)
    result = execute_tool(
        manifest,
        "open_cpacs_summary",
        {"cpacs_path": str(FIXTURE_PATH)},
    )
    summary = json.loads(result.content[0]["text"])
    return {
        "case_study": CASE_STUDY_ID,
        "report": report,
        "result": {
            "manifest_tool_names": list(manifest.tool_names),
            "open_cpacs_summary": summary,
        },
        "status": "passed",
    }


def main() -> None:
    """Run the TiGL case study and print the JSON payload."""
    print(json.dumps(run_case_study(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

"""Ingest the TiGL helper package into standard case-study artifacts.

This script keeps the handoff deliberately simple:

1. verify the checked-in helper package, fixture, and scaffold wrapper exist,
2. probe for the real TiGL and TiXI Python bindings,
3. write the generated facade to `generated_facade.py`, and
4. write the raw scaffold report to `scaffold_report.json`.
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

CASE_STUDY_ID = "tigl_cpacs"
REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPO_ROOT / "case_studies" / "support" / CASE_STUDY_ID
ARTIFACT_ROOT = REPO_ROOT / "artifacts" / "case_studies" / CASE_STUDY_ID
GENERATED_FACADE_PATH = ARTIFACT_ROOT / "generated_facade.py"
REPORT_PATH = ARTIFACT_ROOT / "scaffold_report.json"
SCAFFOLD_PATH = SOURCE_ROOT / "commands" / "scaffold_tigl_cpacs.sh"
PACKAGE_ROOT = SOURCE_ROOT / "tigl_support"
FIXTURE_PATH = SOURCE_ROOT / "fixtures" / "CPACS_30_D150.xml"


def main() -> None:
    """Run the TiGL ingest step and print the stable JSON payload."""
    for required_path in (
        SCAFFOLD_PATH,
        PACKAGE_ROOT / "__init__.py",
        PACKAGE_ROOT / "core.py",
        FIXTURE_PATH,
    ):
        if not required_path.exists():
            raise FileNotFoundError(f"Missing checked-in case-study support file: {required_path}")

    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    for stale_path in (GENERATED_FACADE_PATH, REPORT_PATH):
        if stale_path.exists():
            stale_path.unlink()

    payload: dict[str, object] = {
        "artifacts": {
            "generated_facade": str(GENERATED_FACADE_PATH),
            "scaffold_report": str(REPORT_PATH),
        },
        "case_study": CASE_STUDY_ID,
        "fixture_path": str(FIXTURE_PATH),
        "phase": "ingest",
        "source_root": str(SOURCE_ROOT),
    }

    try:
        importlib.import_module("tigl3.tigl3wrapper")
        importlib.import_module("tixi3.tixi3wrapper")
    except Exception as exc:
        payload["reason"] = f"Import probe failed for TiGL/TiXI bindings: {exc}"
        payload["status"] = "skipped_unavailable"
        print(json.dumps(payload, indent=2, sort_keys=True))
        return

    env = dict(os.environ)
    pythonpath_entries = [
        str((REPO_ROOT / "src").resolve()),
        str(PACKAGE_ROOT.parent.resolve()),
    ]
    if env.get("PYTHONPATH"):
        pythonpath_entries.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(pythonpath_entries)
    env.setdefault("PYTHON_BIN", sys.executable)

    completed = subprocess.run(
        ["sh", str(SCAFFOLD_PATH.resolve()), str(GENERATED_FACADE_PATH)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    report = json.loads(completed.stdout)
    REPORT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    payload["report"] = report
    payload["status"] = "passed"
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

"""Ingest the TiGL helper package wrapper and persist the generated facade.

This script keeps the TiGL case-study ingest path transparent:

1. verify the checked-in helper package, fixture, and scaffold wrapper exist,
2. probe for the real TiGL and TiXI Python bindings,
3. run the public package scaffold flow against the helper package, and
4. persist the scaffold report for the follow-on use step.
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
STATE_PATH = ARTIFACT_ROOT / "ingest_state.json"
GENERATED_FACADE_PATH = ARTIFACT_ROOT / "generated_tigl_facade.py"
SCAFFOLD_PATH = SOURCE_ROOT / "commands" / "scaffold_tigl_cpacs.sh"
PACKAGE_ROOT = SOURCE_ROOT / "tigl_support"
FIXTURE_PATH = SOURCE_ROOT / "fixtures" / "CPACS_30_D150.xml"


def main() -> None:
    """Run the TiGL ingest step and print the persisted state payload."""
    for required_path in (
        SCAFFOLD_PATH,
        PACKAGE_ROOT / "__init__.py",
        PACKAGE_ROOT / "core.py",
        FIXTURE_PATH,
    ):
        if not required_path.exists():
            raise FileNotFoundError(f"Missing checked-in case-study support file: {required_path}")

    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)

    payload: dict[str, object] = {
        "case_study": CASE_STUDY_ID,
        "fixture_path": str(FIXTURE_PATH),
        "generated_facade": str(GENERATED_FACADE_PATH),
        "phase": "ingest",
        "source_root": str(SOURCE_ROOT),
        "state_path": str(STATE_PATH),
    }

    try:
        importlib.import_module("tigl3.tigl3wrapper")
        importlib.import_module("tixi3.tixi3wrapper")
    except Exception as exc:
        payload["reason"] = f"Import probe failed for TiGL/TiXI bindings: {exc}"
        payload["status"] = "skipped_unavailable"
        STATE_PATH.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
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

    payload["report"] = json.loads(completed.stdout)
    payload["status"] = "passed"

    STATE_PATH.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

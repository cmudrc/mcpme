"""Ingest the SU2 command surface and persist the generated facade.

This script is intentionally linear so contributors can read the real
ingestion path top to bottom:

1. verify the checked-in support wrappers are present,
2. probe whether `SU2_CFD` is available on this machine,
3. run the public scaffold CLI through the checked-in shell wrapper, and
4. persist the scaffold report and generated facade location for `use.py`.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

CASE_STUDY_ID = "su2_cli"
REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPO_ROOT / "case_studies" / "support" / CASE_STUDY_ID
ARTIFACT_ROOT = REPO_ROOT / "artifacts" / "case_studies" / CASE_STUDY_ID
STATE_PATH = ARTIFACT_ROOT / "ingest_state.json"
GENERATED_FACADE_PATH = ARTIFACT_ROOT / "generated_su2_facade.py"
SCAFFOLD_PATH = SOURCE_ROOT / "commands" / "scaffold_su2_cli.sh"
PROBE_WRAPPER_PATH = SOURCE_ROOT / "commands" / "su2_cfd.sh"


def main() -> None:
    """Run the SU2 ingest step and print the persisted state payload."""
    if not SCAFFOLD_PATH.exists():
        raise FileNotFoundError(f"Missing checked-in case-study support file: {SCAFFOLD_PATH}")
    if not PROBE_WRAPPER_PATH.exists():
        raise FileNotFoundError(f"Missing checked-in case-study support file: {PROBE_WRAPPER_PATH}")

    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)

    payload: dict[str, object] = {
        "case_study": CASE_STUDY_ID,
        "generated_facade": str(GENERATED_FACADE_PATH),
        "phase": "ingest",
        "source_root": str(SOURCE_ROOT),
        "state_path": str(STATE_PATH),
    }

    if shutil.which("SU2_CFD") is None:
        payload["reason"] = "Availability probe command is unavailable on PATH: 'SU2_CFD'"
        payload["status"] = "skipped_unavailable"
        STATE_PATH.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(json.dumps(payload, indent=2, sort_keys=True))
        return

    env = dict(os.environ)
    pythonpath_entries = [str((REPO_ROOT / "src").resolve())]
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

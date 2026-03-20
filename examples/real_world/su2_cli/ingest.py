"""Ingest the SU2 command surface into standard real-world example artifacts.

This script keeps the handoff deliberately simple:

1. verify the checked-in command wrappers are present,
2. probe whether `SU2_CFD` is available on this machine,
3. write the generated facade to `generated_facade.py`, and
4. write the raw scaffold report to `scaffold_report.json`.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

CASE_STUDY_ID = "su2_cli"
REPO_ROOT = Path(__file__).resolve().parents[3]
SOURCE_ROOT = REPO_ROOT / "examples" / "support" / "real_world" / CASE_STUDY_ID
ARTIFACT_ROOT = REPO_ROOT / "artifacts" / "examples" / "real_world" / CASE_STUDY_ID
GENERATED_FACADE_PATH = ARTIFACT_ROOT / "generated_facade.py"
REPORT_PATH = ARTIFACT_ROOT / "scaffold_report.json"
SCAFFOLD_PATH = SOURCE_ROOT / "commands" / "scaffold_su2_cli.sh"
PROBE_WRAPPER_PATH = SOURCE_ROOT / "commands" / "su2_cfd.sh"


def main() -> None:
    """Run the SU2 ingest step and print the stable JSON payload."""
    # The wrapper scripts are checked-in teaching assets, so verify they are
    # present before doing any environment-specific probing.
    if not SCAFFOLD_PATH.exists():
        raise FileNotFoundError(
            f"Missing checked-in real-world example support file: {SCAFFOLD_PATH}"
        )
    if not PROBE_WRAPPER_PATH.exists():
        raise FileNotFoundError(
            f"Missing checked-in real-world example support file: {PROBE_WRAPPER_PATH}"
        )

    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    # Remove any previous outputs so the artifact directory reflects this run
    # only and not a stale earlier scaffold.
    for stale_path in (GENERATED_FACADE_PATH, REPORT_PATH):
        if stale_path.exists():
            stale_path.unlink()

    # Keep the output contract identical whether we pass or skip.
    payload: dict[str, object] = {
        "artifacts": {
            "generated_facade": str(GENERATED_FACADE_PATH),
            "scaffold_report": str(REPORT_PATH),
        },
        "case_study": CASE_STUDY_ID,
        "phase": "ingest",
        "source_root": str(SOURCE_ROOT),
    }

    # Probe the real upstream executable before scaffolding so an unavailable
    # SU2 install reports a direct and readable skip reason.
    if shutil.which("SU2_CFD") is None:
        payload["reason"] = "Availability probe command is unavailable on PATH: 'SU2_CFD'"
        payload["status"] = "skipped_unavailable"
        print(json.dumps(payload, indent=2, sort_keys=True))
        return

    env = dict(os.environ)
    # The wrapper shells out to `python -m mcpcraft.cli`, so point it at this
    # checkout's source tree explicitly.
    pythonpath_entries = [str((REPO_ROOT / "src").resolve())]
    if env.get("PYTHONPATH"):
        pythonpath_entries.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(pythonpath_entries)
    env.setdefault("PYTHON_BIN", sys.executable)

    # Use the checked-in shell wrapper so the real-world example documents a public,
    # reproducible scaffold entry point.
    completed = subprocess.run(
        ["sh", str(SCAFFOLD_PATH.resolve()), str(GENERATED_FACADE_PATH)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    report = json.loads(completed.stdout)
    # Persist the report verbatim as the inspectable record of what scaffold
    # discovered about the SU2 command surface.
    REPORT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    payload["report"] = report
    payload["status"] = "passed"
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

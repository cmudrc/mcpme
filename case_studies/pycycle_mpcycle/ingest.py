"""Ingest the pyCycle `MPCycle` wrapper and persist the generated facade.

This script deliberately keeps the ingestion story visible:

1. confirm the engineering `pycycle.api` package is importable,
2. run the checked-in public scaffold command,
3. inspect the scaffold report for the session tools we care about, and
4. persist that report for the follow-on use step.
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

CASE_STUDY_ID = "pycycle_mpcycle"
REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPO_ROOT / "case_studies" / "support" / CASE_STUDY_ID
ARTIFACT_ROOT = REPO_ROOT / "artifacts" / "case_studies" / CASE_STUDY_ID
STATE_PATH = ARTIFACT_ROOT / "ingest_state.json"
GENERATED_FACADE_PATH = ARTIFACT_ROOT / "generated_pycycle_facade.py"
SCAFFOLD_PATH = SOURCE_ROOT / "commands" / "scaffold_pycycle_mpcycle.sh"


def main() -> None:
    """Run the pyCycle ingest step and print the persisted state payload."""
    if not SCAFFOLD_PATH.exists():
        raise FileNotFoundError(f"Missing checked-in case-study support file: {SCAFFOLD_PATH}")

    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)

    payload: dict[str, object] = {
        "case_study": CASE_STUDY_ID,
        "generated_facade": str(GENERATED_FACADE_PATH),
        "phase": "ingest",
        "source_root": str(SOURCE_ROOT),
        "state_path": str(STATE_PATH),
    }

    try:
        importlib.import_module("pycycle.api")
    except Exception as exc:
        payload["reason"] = f"Import probe failed for 'pycycle.api': {exc}"
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

    report = json.loads(completed.stdout)
    tool_names: dict[str, str] = {}
    for entry in report.get("generatedTools", []):
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        source = entry.get("source")
        if not isinstance(name, str) or not isinstance(source, str):
            continue
        if name.startswith("create_") and source.endswith(".MPCycle"):
            tool_names["create"] = name
        if name.startswith("mpcycle_") and source.endswith(".MPCycle.pyc_add_cycle_param"):
            tool_names["add_cycle_param"] = name
        if name.startswith("close_") and source.endswith(".MPCycle"):
            tool_names["close"] = name

    if set(tool_names) != {"create", "add_cycle_param", "close"}:
        raise ValueError(
            "Expected scaffold report to expose create, add_cycle_param, and close tools "
            f"for MPCycle; found {tool_names!r}."
        )

    payload["report"] = report
    payload["status"] = "passed"
    payload["tool_names"] = tool_names

    STATE_PATH.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

"""Case study for ingesting, persisting, and then using pyCycle `MPCycle`.

## Introduction

This case study shows how `mcpme` can carve a useful session-oriented wrapper
out of a real engineering Python package without teaching the library
anything pyCycle-specific. The workflow mirrors a more realistic integration
path: ingest the package once, persist the generated facade, and then execute
the wrapped session lifecycle from that persisted artifact.

## Preset Environment

The case-study-specific public scaffold command is checked in under
`case_studies/support/pycycle_mpcycle/commands/`. Run
`case_studies/pycycle_mpcycle/ingest.py` first to generate and persist the
facade under `artifacts/case_studies/pycycle_mpcycle/`, then run
`case_studies/pycycle_mpcycle/use.py` to build a manifest from that persisted
facade and exercise the generated tools.

## Technical Implementation

- `ingest.py` requires `import pycycle.api` to succeed so the case study only
  runs against the engineering `om-pycycle` distribution.
- The ingest step runs the public scaffold CLI through a checked-in shell
  wrapper and persists the discovered tool names for the `MPCycle` lifecycle.
- `use.py` reads that persisted ingest state instead of re-running ingestion.
- The use step creates an `MPCycle` session, calls `pyc_add_cycle_param`, and
  closes the session through the generated runtime bindings.

## Expected Results

When the engineering pyCycle package is available, `ingest.py` prints a
`passed` payload with the scaffold report and persisted tool names, and
`use.py` prints a `passed` payload with the session lifecycle outputs. On
machines without `pycycle.api`, the ingest step persists a
`skipped_unavailable` state and the use step reports the same skip reason
without failing.

## Availability

This case study requires the OpenMDAO pyCycle distribution, installed from the
`om-pycycle` package while still importing as `pycycle`. If `pycycle.api`
cannot be imported, both scripts skip cleanly.

## References

- ``README.md``
- ``case_studies/README.md``
- ``case_studies/pycycle_mpcycle/ingest.py``
- ``case_studies/support/pycycle_mpcycle/commands/scaffold_pycycle_mpcycle.sh``
- ``docs/quickstart.rst``
- ``docs/specification.rst``
"""

from __future__ import annotations

import json
from pathlib import Path

from mcpme import build_manifest, execute_tool

CASE_STUDY_ID = "pycycle_mpcycle"
REPO_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_ROOT = REPO_ROOT / "artifacts" / "case_studies" / CASE_STUDY_ID
STATE_PATH = ARTIFACT_ROOT / "ingest_state.json"


def main() -> None:
    """Run the persisted pyCycle use step and print the stable JSON payload."""
    if not STATE_PATH.exists():
        raise FileNotFoundError(
            f"Missing persisted ingest state: {STATE_PATH}. "
            "Run case_studies/pycycle_mpcycle/ingest.py first."
        )

    ingest_state = json.loads(STATE_PATH.read_text(encoding="utf-8"))

    if ingest_state["status"] == "skipped_unavailable":
        payload = {
            "case_study": CASE_STUDY_ID,
            "phase": "use",
            "reason": ingest_state["reason"],
            "status": "skipped_unavailable",
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return

    generated_facade = Path(str(ingest_state["generated_facade"]))
    manifest = build_manifest(targets=[generated_facade], artifact_root=ARTIFACT_ROOT)
    tool_names = ingest_state["tool_names"]

    create_result = execute_tool(manifest, tool_names["create"], {})
    create_record = json.loads(create_result.content[0]["text"])
    session_id = create_record["session_id"]

    add_param_result = execute_tool(
        manifest,
        tool_names["add_cycle_param"],
        {"name": "FAR", "session_id": session_id, "val": 0.02},
    )
    add_param_record = json.loads(add_param_result.content[0]["text"])

    close_result = execute_tool(manifest, tool_names["close"], {"session_id": session_id})
    close_record = json.loads(close_result.content[0]["text"])
    if close_record.get("success") is not True:
        raise ValueError("Expected the generated close wrapper to report success.")

    payload = {
        "case_study": CASE_STUDY_ID,
        "ingest_state": {
            "generated_facade": str(generated_facade),
            "state_path": str(STATE_PATH),
            "tool_names": tool_names,
        },
        "phase": "use",
        "report": ingest_state["report"],
        "result": {
            "close": close_record,
            "create": create_record,
            "manifest_tool_names": list(manifest.tool_names),
            "pyc_add_cycle_param": add_param_record,
        },
        "status": "passed",
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

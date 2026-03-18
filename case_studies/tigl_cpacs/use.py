"""Case study for ingesting, persisting, and then using a TiGL CPACS helper.

## Introduction

This case study tackles a more awkward upstream than the small core examples:
TiGL workflows revolve around native bindings, CPACS files, and handles that
are not themselves JSON-friendly. Instead of baking that complexity into
`mcpme`, the case study keeps a tiny helper package checked in, ingests that
helper through the public CLI, persists the generated facade, and then uses
that persisted facade through the normal public runtime.

## Preset Environment

The helper package, the public scaffold wrapper, and the real D150 CPACS XML
fixture all live under `case_studies/support/tigl_cpacs/`. Run
`case_studies/tigl_cpacs/ingest.py` first to scaffold and persist the helper
facade under `artifacts/case_studies/tigl_cpacs/`, then run
`case_studies/tigl_cpacs/use.py` to build a manifest from that persisted
facade and execute the helper against the checked-in CPACS input.

## Technical Implementation

- `ingest.py` verifies that the real `tigl3` and `tixi3` Python bindings are
  importable before attempting any scaffold work.
- The ingest step runs the public package scaffold CLI through a checked-in
  shell wrapper against the checked-in `tigl_support` helper package.
- `use.py` adds the checked-in helper package parent to `sys.path`, reads the
  persisted ingest state, and builds a manifest from the saved generated
  facade.
- The use step executes the generated `open_cpacs_summary` tool against a real
  checked-in CPACS XML file and returns a JSON-friendly summary.

## Expected Results

When the TiGL and TiXI bindings are available, `ingest.py` prints a `passed`
payload with the scaffold report and persisted facade location, and `use.py`
prints a `passed` payload with the CPACS summary produced through the real
bindings. On machines without those bindings, the ingest step persists a
`skipped_unavailable` state and the use step reports the same skip reason
without failing.

## Availability

This case study requires the real `tigl3` and `tixi3` Python bindings, which
are typically installed outside the base Python toolchain. The repository does
not install them automatically, so both scripts are expected to skip cleanly
on many machines.

## References

- ``README.md``
- ``case_studies/README.md``
- ``case_studies/tigl_cpacs/ingest.py``
- ``case_studies/support/tigl_cpacs/commands/scaffold_tigl_cpacs.sh``
- ``case_studies/support/tigl_cpacs/tigl_support/__init__.py``
- ``case_studies/support/tigl_cpacs/tigl_support/core.py``
- ``case_studies/support/tigl_cpacs/fixtures/CPACS_30_D150.xml``
- ``docs/quickstart.rst``
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from mcpme import build_manifest, execute_tool

CASE_STUDY_ID = "tigl_cpacs"
REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPO_ROOT / "case_studies" / "support" / CASE_STUDY_ID
ARTIFACT_ROOT = REPO_ROOT / "artifacts" / "case_studies" / CASE_STUDY_ID
STATE_PATH = ARTIFACT_ROOT / "ingest_state.json"
PACKAGE_ROOT = SOURCE_ROOT / "tigl_support"


def main() -> None:
    """Run the persisted TiGL use step and print the stable JSON payload."""
    if not STATE_PATH.exists():
        raise FileNotFoundError(
            f"Missing persisted ingest state: {STATE_PATH}. "
            "Run case_studies/tigl_cpacs/ingest.py first."
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

    package_parent = str(PACKAGE_ROOT.parent.resolve())
    if package_parent not in sys.path:
        sys.path.insert(0, package_parent)

    generated_facade = Path(str(ingest_state["generated_facade"]))
    manifest = build_manifest(targets=[generated_facade], artifact_root=ARTIFACT_ROOT)
    summary_result = execute_tool(
        manifest,
        "open_cpacs_summary",
        {"cpacs_path": ingest_state["fixture_path"]},
    )
    summary_record = json.loads(summary_result.content[0]["text"])

    payload = {
        "case_study": CASE_STUDY_ID,
        "ingest_state": {
            "fixture_path": ingest_state["fixture_path"],
            "generated_facade": str(generated_facade),
            "state_path": str(STATE_PATH),
        },
        "phase": "use",
        "report": ingest_state["report"],
        "result": {
            "manifest_tool_names": list(manifest.tool_names),
            "open_cpacs_summary": summary_record,
        },
        "status": "passed",
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

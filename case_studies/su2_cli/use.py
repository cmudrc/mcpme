"""Case study for ingesting, persisting, and then using the SU2 CLI wrapper.

## Introduction

This case study models the shape of a real heavyweight CLI integration more
closely than the smaller examples: first ingest the upstream surface into a
generated facade, persist that generated artifact, and only then use it
through the normal `mcpme` runtime. The split is deliberate so contributors
can inspect the generated wrapper before the wrapped command is executed.

## Preset Environment

The checked-in command surface for this case study lives under
`case_studies/support/su2_cli/commands/`. Run `case_studies/su2_cli/ingest.py`
to scaffold and persist the facade under `artifacts/case_studies/su2_cli/`,
then run `case_studies/su2_cli/use.py` to build a manifest from that persisted
facade and exercise the wrapped CLI.

## Technical Implementation

- `ingest.py` probes for `SU2_CFD`, runs the public scaffold CLI through the
  checked-in shell wrapper, and writes `ingest_state.json` under the case-study
  artifact directory.
- `use.py` reads that persisted ingest state rather than scaffolding again.
- The use step builds a manifest from the saved generated facade through the
  top-level public API and executes the generated wrapper with
  `extra_argv=["-h"]`.
- The result payload retains both the scaffold report and the wrapped help-path
  execution evidence.

## Expected Results

When SU2 is available, `ingest.py` prints a `passed` payload with the scaffold
report, and `use.py` prints a `passed` payload with the manifest tool names and
the wrapped help-path result. On machines without SU2 installed, the ingest
step persists a `skipped_unavailable` state and the use step reports the same
skip reason without failing.

## Availability

This case study requires the `SU2_CFD` executable to be available on `PATH`.
The repository does not install SU2 automatically, so both scripts are
expected to report `skipped_unavailable` cleanly on many machines.

## References

- ``README.md``
- ``case_studies/README.md``
- ``case_studies/su2_cli/ingest.py``
- ``case_studies/support/su2_cli/commands/su2_cfd.sh``
- ``case_studies/support/su2_cli/commands/scaffold_su2_cli.sh``
- ``docs/quickstart.rst``
- ``docs/specification.rst``
"""

from __future__ import annotations

import json
from pathlib import Path

from mcpme import build_manifest, execute_tool

CASE_STUDY_ID = "su2_cli"
REPO_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_ROOT = REPO_ROOT / "artifacts" / "case_studies" / CASE_STUDY_ID
STATE_PATH = ARTIFACT_ROOT / "ingest_state.json"


def main() -> None:
    """Run the persisted SU2 use step and print the stable JSON payload."""
    if not STATE_PATH.exists():
        raise FileNotFoundError(
            f"Missing persisted ingest state: {STATE_PATH}. "
            "Run case_studies/su2_cli/ingest.py first."
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
    tool_result = execute_tool(manifest, "run_su2_cfd", {"extra_argv": ["-h"]}).to_mcp_result()

    if "SU2_CFD" not in json.dumps(tool_result, sort_keys=True):
        raise ValueError("Expected the wrapped SU2 help output to mention 'SU2_CFD'.")

    payload = {
        "case_study": CASE_STUDY_ID,
        "ingest_state": {
            "generated_facade": str(generated_facade),
            "state_path": str(STATE_PATH),
        },
        "phase": "use",
        "report": ingest_state["report"],
        "result": {
            "manifest_tool_names": list(manifest.tool_names),
            "run_su2_cfd": tool_result,
        },
        "status": "passed",
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

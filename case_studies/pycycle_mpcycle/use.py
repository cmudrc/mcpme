"""Case study for ingesting, serving, and then using pyCycle `MPCycle`.

## Introduction

This case study shows how `mcpme` can carve a useful session-oriented wrapper
out of a real engineering Python package without teaching the library
anything pyCycle-specific. The workflow mirrors a more realistic integration
path: ingest the package once, persist the generated facade with a standard
scaffold report, and then drive the wrapped session lifecycle through MCP.

## Preset Environment

The case-study-specific public scaffold command is checked in under
`case_studies/support/pycycle_mpcycle/commands/`. Run
`case_studies/pycycle_mpcycle/ingest.py` first to write `generated_facade.py`
and `scaffold_report.json` under `artifacts/case_studies/pycycle_mpcycle/`,
`case_studies/pycycle_mpcycle/serve.py` to expose that generated facade over
stdio MCP, and `case_studies/pycycle_mpcycle/use.py` separately to exercise
the same generated tools through MCP requests without launching `serve.py`.

## Technical Implementation

- `ingest.py` requires `import pycycle.api` to succeed so the case study only
  runs against the engineering `om-pycycle` distribution.
- The ingest step runs the public scaffold CLI through a checked-in shell
  wrapper and writes the deterministic artifact pair `generated_facade.py` and
  `scaffold_report.json`.
- `serve.py` loads the saved generated facade through the public API and serves
  it over stdio with `mcpme.serve_stdio`.
- `use.py` builds an in-process `mcpme.McpServer` from the saved facade, sends
  `initialize`, `tools/list`, and `tools/call` requests, then exercises the
  create/add-parameter/close lifecycle through the MCP runtime.

## Expected Results

When the engineering pyCycle package is available, `ingest.py` prints a
`passed` payload with the scaffold report, `serve.py` can expose the generated
facade over stdio MCP, and `use.py` prints a `passed` payload with the session
lifecycle outputs. On machines without `pycycle.api`, the ingest step reports
`skipped_unavailable` and the use step reports the same skip reason without
requiring any bespoke handoff file.

## Availability

This case study requires the OpenMDAO pyCycle distribution, installed from the
`om-pycycle` package while still importing as `pycycle`. If `pycycle.api`
cannot be imported, the case study skips cleanly.

## References

- ``README.md``
- ``case_studies/README.md``
- ``case_studies/pycycle_mpcycle/ingest.py``
- ``case_studies/pycycle_mpcycle/serve.py``
- ``case_studies/support/pycycle_mpcycle/commands/scaffold_pycycle_mpcycle.sh``
- ``docs/quickstart.rst``
- ``docs/specification.rst``
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

from mcpme import McpServer, build_manifest

CASE_STUDY_ID = "pycycle_mpcycle"
REPO_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_ROOT = REPO_ROOT / "artifacts" / "case_studies" / CASE_STUDY_ID
GENERATED_FACADE_PATH = ARTIFACT_ROOT / "generated_facade.py"
REPORT_PATH = ARTIFACT_ROOT / "scaffold_report.json"


def _load_server() -> McpServer:
    """Build an MCP server from the saved generated facade."""
    manifest = build_manifest(targets=[GENERATED_FACADE_PATH], artifact_root=ARTIFACT_ROOT)
    return McpServer(manifest)


def main() -> None:
    """Exercise the generated pyCycle facade through in-process MCP requests."""
    if not GENERATED_FACADE_PATH.exists():
        try:
            # Reuse the ingest availability probe so a machine without pyCycle
            # skips cleanly instead of failing with a missing-artifact error.
            importlib.import_module("pycycle.api")
        except Exception as exc:
            payload = {
                "case_study": CASE_STUDY_ID,
                "phase": "use",
                "reason": f"Import probe failed for 'pycycle.api': {exc}",
                "status": "skipped_unavailable",
            }
            print(json.dumps(payload, indent=2, sort_keys=True))
            return
        raise FileNotFoundError(
            f"Missing generated facade artifact: {GENERATED_FACADE_PATH}. "
            "Run case_studies/pycycle_mpcycle/ingest.py first."
        )

    # Treat the scaffold report as part of the contract for a complete ingest.
    if not REPORT_PATH.exists():
        raise FileNotFoundError(
            f"Missing scaffold report artifact: {REPORT_PATH}. "
            "Run case_studies/pycycle_mpcycle/ingest.py first."
        )

    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    server = _load_server()

    # Keep the MCP sequence explicit while leaving `serve.py` as a separate
    # stdio demo entrypoint.
    initialize = server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    if initialize is None or "error" in initialize:
        raise RuntimeError(f"pyCycle MCP initialize failed: {initialize}")

    server.handle_request({"jsonrpc": "2.0", "method": "notifications/initialized"})

    tools_list = server.handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    if tools_list is None or "error" in tools_list:
        raise RuntimeError(f"pyCycle MCP tools/list failed: {tools_list}")

    tool_names = [
        tool["name"]
        for tool in tools_list["result"]["tools"]
        if isinstance(tool, dict) and isinstance(tool.get("name"), str)
    ]
    for expected_name in ("create_mpcycle", "mpcycle_pyc_add_cycle_param", "close_mpcycle"):
        if expected_name not in tool_names:
            raise ValueError(
                f"Expected the served tool list to include {expected_name!r}; got {tool_names!r}."
            )

    # Create a server-side session first; subsequent tool calls thread that
    # session identifier through the generated wrappers.
    create_call = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"arguments": {}, "name": "create_mpcycle"},
        }
    )
    if create_call is None or "error" in create_call:
        raise RuntimeError(f"pyCycle MCP create call failed: {create_call}")
    create_record = json.loads(create_call["result"]["content"][0]["text"])
    session_id = create_record["session_id"]

    # Exercise a representative mutating tool against that saved session.
    add_param_call = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "arguments": {"name": "FAR", "session_id": session_id, "val": 0.02},
                "name": "mpcycle_pyc_add_cycle_param",
            },
        }
    )
    if add_param_call is None or "error" in add_param_call:
        raise RuntimeError(f"pyCycle MCP add-cycle-param call failed: {add_param_call}")
    add_param_record = json.loads(add_param_call["result"]["content"][0]["text"])

    # Close the session explicitly to demonstrate the full lifecycle that the
    # generated facade exposes.
    close_call = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "arguments": {"session_id": session_id},
                "name": "close_mpcycle",
            },
        }
    )
    if close_call is None or "error" in close_call:
        raise RuntimeError(f"pyCycle MCP close call failed: {close_call}")
    close_record = json.loads(close_call["result"]["content"][0]["text"])

    # A successful close call is our simplest proof that the lifecycle stayed
    # coherent all the way through teardown.
    if close_record.get("success") is not True:
        raise ValueError("Expected the served close wrapper to report success.")

    payload = {
        "artifacts": {
            "generated_facade": str(GENERATED_FACADE_PATH),
            "scaffold_report": str(REPORT_PATH),
        },
        "case_study": CASE_STUDY_ID,
        "mcp_session": {
            "server_info": initialize["result"]["serverInfo"],
            "tool_names": tool_names,
        },
        "phase": "use",
        "report": report,
        "result": {
            "close": close_record,
            "create": create_record,
            "pyc_add_cycle_param": add_param_record,
        },
        "status": "passed",
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

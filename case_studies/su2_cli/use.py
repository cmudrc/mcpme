"""Case study for ingesting, serving, and then using the SU2 CLI wrapper.

## Introduction

This case study models the shape of a real heavyweight CLI integration more
closely than the smaller examples: first ingest the upstream surface into a
generated facade, persist that generated artifact with a standard scaffold
report, and then exercise that saved facade through MCP requests. The split is
deliberate so contributors can inspect the generated wrapper before the wrapped
command is executed.

## Preset Environment

The checked-in command surface for this case study lives under
`case_studies/support/su2_cli/commands/`. Run `case_studies/su2_cli/ingest.py`
to write `generated_facade.py` and `scaffold_report.json` under
`artifacts/case_studies/su2_cli/`, `case_studies/su2_cli/serve.py` to expose
that generated facade as an MCP server over stdio, and
`case_studies/su2_cli/use.py` separately to exercise the same generated
facade through MCP requests without launching `serve.py`.

## Technical Implementation

- `ingest.py` probes for `SU2_CFD`, runs the public scaffold CLI through the
  checked-in shell wrapper, and writes the deterministic artifact pair
  `generated_facade.py` and `scaffold_report.json`.
- `serve.py` loads the saved generated facade through the public API and serves
  it over stdio with `mcpwrap.serve_stdio`.
- `use.py` reads the standard artifact paths, builds an in-process
  `mcpwrap.McpServer` from the saved facade, sends `initialize`, `tools/list`,
  and `tools/call` requests, and captures the JSON-RPC responses.
- The result payload retains both the raw scaffold report and the wrapped
  help-path execution evidence returned by the MCP runtime.

## Expected Results

When SU2 is available, `ingest.py` prints a `passed` payload with the scaffold
report, `serve.py` can expose the generated facade over stdio MCP, and
`use.py` prints a `passed` payload with the served tool names and the wrapped
help-path result. On machines without SU2 installed, the ingest step reports
`skipped_unavailable` and the use step reports the same skip reason without
requiring any bespoke handoff file.

## Availability

This case study requires the `SU2_CFD` executable to be available on `PATH`.
The repository does not install SU2 automatically, so the case study is
expected to skip cleanly on many machines.

## References

- ``README.md``
- ``case_studies/README.md``
- ``case_studies/su2_cli/ingest.py``
- ``case_studies/su2_cli/serve.py``
- ``case_studies/support/su2_cli/commands/su2_cfd.sh``
- ``case_studies/support/su2_cli/commands/scaffold_su2_cli.sh``
- ``docs/quickstart.rst``
- ``docs/specification.rst``
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from mcpwrap import McpServer, build_manifest

CASE_STUDY_ID = "su2_cli"
REPO_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_ROOT = REPO_ROOT / "artifacts" / "case_studies" / CASE_STUDY_ID
GENERATED_FACADE_PATH = ARTIFACT_ROOT / "generated_facade.py"
REPORT_PATH = ARTIFACT_ROOT / "scaffold_report.json"


def _load_server() -> McpServer:
    """Build an MCP server from the saved generated facade."""
    manifest = build_manifest(targets=[GENERATED_FACADE_PATH], artifact_root=ARTIFACT_ROOT)
    return McpServer(manifest)


def main() -> None:
    """Exercise the generated SU2 facade through in-process MCP requests."""
    if not GENERATED_FACADE_PATH.exists():
        # Mirror the ingest availability check so missing artifacts become
        # readable skips on machines without SU2 installed.
        if shutil.which("SU2_CFD") is None:
            payload = {
                "case_study": CASE_STUDY_ID,
                "phase": "use",
                "reason": "Availability probe command is unavailable on PATH: 'SU2_CFD'",
                "status": "skipped_unavailable",
            }
            print(json.dumps(payload, indent=2, sort_keys=True))
            return
        raise FileNotFoundError(
            f"Missing generated facade artifact: {GENERATED_FACADE_PATH}. "
            "Run case_studies/su2_cli/ingest.py first."
        )

    # The use step expects the standard two-file handoff written by ingest.
    if not REPORT_PATH.exists():
        raise FileNotFoundError(
            f"Missing scaffold report artifact: {REPORT_PATH}. "
            "Run case_studies/su2_cli/ingest.py first."
        )

    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    server = _load_server()

    # Keep the MCP exchange explicit even though the use step now runs
    # separately from the stdio serving demo.
    initialize = server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    if initialize is None or "error" in initialize:
        raise RuntimeError(f"SU2 MCP initialize failed: {initialize}")

    server.handle_request({"jsonrpc": "2.0", "method": "notifications/initialized"})

    tools_list = server.handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    if tools_list is None or "error" in tools_list:
        raise RuntimeError(f"SU2 MCP tools/list failed: {tools_list}")

    tool_names = [
        tool["name"]
        for tool in tools_list["result"]["tools"]
        if isinstance(tool, dict) and isinstance(tool.get("name"), str)
    ]
    if "run_su2_cfd" not in tool_names:
        raise ValueError(
            f"Expected the served tool list to include 'run_su2_cfd'; got {tool_names!r}."
        )

    # Use `-h` as a cheap, deterministic smoke test that still exercises the
    # real wrapped CLI entry point.
    tool_call = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"arguments": {"extra_argv": ["-h"]}, "name": "run_su2_cfd"},
        }
    )
    if tool_call is None or "error" in tool_call:
        raise RuntimeError(f"SU2 MCP tools/call failed: {tool_call}")

    tool_result = tool_call["result"]
    # Sanity-check that the help path reached the real upstream executable.
    if "SU2_CFD" not in json.dumps(tool_result, sort_keys=True):
        raise ValueError("Expected the wrapped SU2 help output to mention 'SU2_CFD'.")

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
        "result": {"run_su2_cfd": tool_result},
        "status": "passed",
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

"""Case study for ingesting, serving, and then using a TiGL CPACS helper.

## Introduction

This case study tackles a more awkward upstream than the small core examples:
TiGL workflows revolve around native bindings, CPACS files, and handles that
are not themselves JSON-friendly. Instead of baking that complexity into
`mcpme`, the case study keeps a tiny helper package checked in, ingests that
helper through the public CLI, persists the generated facade with a standard
scaffold report, serves that facade over stdio MCP, and then uses it through a
real MCP client request.

## Preset Environment

The helper package, the public scaffold wrapper, and the real D150 CPACS XML
fixture all live under `case_studies/support/tigl_cpacs/`. Run
`case_studies/tigl_cpacs/ingest.py` first to write `generated_facade.py` and
`scaffold_report.json` under `artifacts/case_studies/tigl_cpacs/`,
`case_studies/tigl_cpacs/serve.py` to expose that generated facade over stdio
MCP, and `case_studies/tigl_cpacs/use.py` to hit that MCP server and execute
the helper against the checked-in CPACS input.

## Technical Implementation

- `ingest.py` verifies that the real `tigl3` and `tixi3` Python bindings are
  importable before attempting any scaffold work.
- The ingest step runs the public package scaffold CLI through a checked-in
  shell wrapper and writes the deterministic artifact pair
  `generated_facade.py` and `scaffold_report.json`.
- `serve.py` adds the checked-in helper package parent to `sys.path`, loads the
  saved generated facade through the public API, and serves it over stdio with
  `mcpme.serve_stdio`.
- `use.py` starts `serve.py`, sends `initialize`, `tools/list`, and
  `tools/call` requests, and captures the TiGL summary through the served MCP
  interface.

## Expected Results

When the TiGL and TiXI bindings are available, `ingest.py` prints a `passed`
payload with the scaffold report, `serve.py` can expose the generated facade
over stdio MCP, and `use.py` prints a `passed` payload with the CPACS summary
produced through the real bindings. On machines without those bindings, the
ingest step reports `skipped_unavailable` and the use step reports the same
skip reason without requiring any bespoke handoff file.

## Availability

This case study requires the real `tigl3` and `tixi3` Python bindings, which
are typically installed outside the base Python toolchain. The repository does
not install them automatically, so the case study is expected to skip cleanly
on many machines.

## References

- ``README.md``
- ``case_studies/README.md``
- ``case_studies/tigl_cpacs/ingest.py``
- ``case_studies/tigl_cpacs/serve.py``
- ``case_studies/support/tigl_cpacs/commands/scaffold_tigl_cpacs.sh``
- ``case_studies/support/tigl_cpacs/tigl_support/__init__.py``
- ``case_studies/support/tigl_cpacs/tigl_support/core.py``
- ``case_studies/support/tigl_cpacs/fixtures/CPACS_30_D150.xml``
- ``docs/quickstart.rst``
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
SERVE_PATH = REPO_ROOT / "case_studies" / CASE_STUDY_ID / "serve.py"
FIXTURE_PATH = SOURCE_ROOT / "fixtures" / "CPACS_30_D150.xml"


def main() -> None:
    """Hit the served TiGL MCP runtime and print the stable JSON payload."""
    if not GENERATED_FACADE_PATH.exists():
        try:
            # Mirror the ingest availability probe so a missing artifact reports
            # a clean skip when the native TiGL stack is simply unavailable.
            importlib.import_module("tigl3.tigl3wrapper")
            importlib.import_module("tixi3.tixi3wrapper")
        except Exception as exc:
            payload = {
                "case_study": CASE_STUDY_ID,
                "phase": "use",
                "reason": f"Import probe failed for TiGL/TiXI bindings: {exc}",
                "status": "skipped_unavailable",
            }
            print(json.dumps(payload, indent=2, sort_keys=True))
            return
        raise FileNotFoundError(
            f"Missing generated facade artifact: {GENERATED_FACADE_PATH}. "
            "Run case_studies/tigl_cpacs/ingest.py first."
        )

    # The use phase depends on the standard artifact pair produced by ingest.
    if not REPORT_PATH.exists():
        raise FileNotFoundError(
            f"Missing scaffold report artifact: {REPORT_PATH}. "
            "Run case_studies/tigl_cpacs/ingest.py first."
        )

    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    env = dict(os.environ)
    pythonpath_entries = [str((REPO_ROOT / "src").resolve())]
    if env.get("PYTHONPATH"):
        pythonpath_entries.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(pythonpath_entries)

    # Spawn the MCP server as a separate process so the case study exercises
    # the same stdio boundary a real client would use.
    server = subprocess.Popen(
        [sys.executable, str(SERVE_PATH)],
        cwd=REPO_ROOT,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if server.stdin is None or server.stdout is None or server.stderr is None:
        raise RuntimeError("Expected stdio pipes when launching the TiGL case-study MCP server.")

    try:
        # Speak the JSON-RPC handshake directly so the protocol flow stays
        # visible to readers instead of being hidden behind a helper client.
        server.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"}) + "\n")
        server.stdin.flush()
        initialize = json.loads(server.stdout.readline())
        if "error" in initialize:
            raise RuntimeError(f"TiGL MCP initialize failed: {initialize['error']}")

        # Notify the server that the client accepted the advertised capabilities.
        server.stdin.write(
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
        )
        server.stdin.flush()

        # Inspect the served tool surface before making any tool call.
        server.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}) + "\n")
        server.stdin.flush()
        tools_list = json.loads(server.stdout.readline())
        if "error" in tools_list:
            raise RuntimeError(f"TiGL MCP tools/list failed: {tools_list['error']}")

        tool_names = [
            tool["name"]
            for tool in tools_list["result"]["tools"]
            if isinstance(tool, dict) and isinstance(tool.get("name"), str)
        ]
        if "open_cpacs_summary" not in tool_names:
            raise ValueError(
                "Expected the served tool list to include 'open_cpacs_summary'; "
                f"got {tool_names!r}."
            )

        # Call the wrapped helper through MCP using the checked-in CPACS input.
        server.stdin.write(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {
                        "arguments": {"cpacs_path": str(FIXTURE_PATH)},
                        "name": "open_cpacs_summary",
                    },
                }
            )
            + "\n"
        )
        server.stdin.flush()
        summary_call = json.loads(server.stdout.readline())
        if "error" in summary_call:
            raise RuntimeError(f"TiGL MCP tools/call failed: {summary_call['error']}")
        summary_record = json.loads(summary_call["result"]["content"][0]["text"])
    finally:
        # Closing stdin lets the stdio server finish naturally once the client
        # has sent all requests.
        if not server.stdin.closed:
            server.stdin.close()
        try:
            return_code = server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            # If the server hangs, kill it so the case study still terminates
            # deterministically in CI.
            server.kill()
            return_code = server.wait(timeout=5)
        server_stderr = server.stderr.read()

    # Surface server stderr on failure so contributors can inspect the exact
    # wrapped-process behavior.
    if return_code != 0:
        raise RuntimeError(
            f"TiGL MCP server exited with code {return_code}.\nstderr:\n{server_stderr}"
        )

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
        "result": {"open_cpacs_summary": summary_record},
        "status": "passed",
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

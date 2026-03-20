"""Real-world example for ingesting, serving, and then using the SU2 CLI wrapper.

## Introduction

This real-world example models the shape of a real heavyweight CLI integration more
closely than the smaller examples: first ingest the upstream surface into a
generated facade, persist that generated artifact with a standard scaffold
report, serve it over stdio MCP, and only then use it through a client
request. The split is deliberate so contributors can inspect the generated
wrapper before the wrapped command is executed.

## Preset Environment

The checked-in command surface for this real-world example lives under
`examples/support/real_world/su2_cli/commands/`. Run `examples/real_world/su2_cli/ingest.py`
to write `generated_facade.py` and `scaffold_report.json` under
`artifacts/examples/real_world/su2_cli/`, `examples/real_world/su2_cli/serve.py` to expose
that generated facade as an MCP server, and `examples/real_world/su2_cli/use.py` to
hit that MCP server and exercise the wrapped CLI.

## Technical Implementation

- `ingest.py` probes for `SU2_CFD`, runs the public scaffold CLI through the
  checked-in shell wrapper, and writes the deterministic artifact pair
  `generated_facade.py` and `scaffold_report.json`.
- `serve.py` loads the saved generated facade through the public API and serves
  it over stdio with `mcpcraft.serve_stdio`.
- `use.py` reads the standard artifact paths, starts `serve.py` as a
  subprocess, sends `initialize`, `tools/list`, and `tools/call` requests, and
  captures the JSON-RPC responses.
- The result payload retains both the raw scaffold report and the wrapped
  help-path execution evidence returned by the served MCP runtime.

## Expected Results

When SU2 is available, `ingest.py` prints a `passed` payload with the scaffold
report, `serve.py` can expose the generated facade over stdio MCP, and
`use.py` prints a `passed` payload with the served tool names and the wrapped
help-path result. On machines without SU2 installed, the ingest step reports
`skipped_unavailable` and the use step reports the same skip reason without
requiring any bespoke handoff file.

## Availability

This real-world example requires the `SU2_CFD` executable to be available on `PATH`.
The repository does not install SU2 automatically, so the real-world example is
expected to skip cleanly on many machines.

## References

- ``README.md``
- ``examples/real_world/README.md``
- ``examples/real_world/su2_cli/ingest.py``
- ``examples/real_world/su2_cli/serve.py``
- ``examples/support/real_world/su2_cli/commands/su2_cfd.sh``
- ``examples/support/real_world/su2_cli/commands/scaffold_su2_cli.sh``
- ``docs/quickstart.rst``
- ``docs/specification.rst``
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
ARTIFACT_ROOT = REPO_ROOT / "artifacts" / "examples" / "real_world" / CASE_STUDY_ID
GENERATED_FACADE_PATH = ARTIFACT_ROOT / "generated_facade.py"
REPORT_PATH = ARTIFACT_ROOT / "scaffold_report.json"
SERVE_PATH = REPO_ROOT / "examples" / "real_world" / CASE_STUDY_ID / "serve.py"


def main() -> None:
    """Hit the served SU2 MCP runtime and print the stable JSON payload."""
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
            "Run examples/real_world/su2_cli/ingest.py first."
        )

    # The use step expects the standard two-file handoff written by ingest.
    if not REPORT_PATH.exists():
        raise FileNotFoundError(
            f"Missing scaffold report artifact: {REPORT_PATH}. "
            "Run examples/real_world/su2_cli/ingest.py first."
        )

    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    env = dict(os.environ)
    pythonpath_entries = [str((REPO_ROOT / "src").resolve())]
    if env.get("PYTHONPATH"):
        pythonpath_entries.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(pythonpath_entries)

    # Start the stdio server in its own process to demonstrate the real client
    # boundary for a wrapped CLI tool.
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
        raise RuntimeError(
            "Expected stdio pipes when launching the SU2 real-world example MCP server."
        )

    try:
        # Manually issue the MCP handshake so the example teaches the protocol
        # shape rather than hiding it behind a helper library.
        server.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"}) + "\n")
        server.stdin.flush()
        initialize = json.loads(server.stdout.readline())
        if "error" in initialize:
            raise RuntimeError(f"SU2 MCP initialize failed: {initialize['error']}")

        # Complete initialization before normal requests.
        server.stdin.write(
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
        )
        server.stdin.flush()

        # Prove which tool names the generated facade exposes before using one.
        server.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}) + "\n")
        server.stdin.flush()
        tools_list = json.loads(server.stdout.readline())
        if "error" in tools_list:
            raise RuntimeError(f"SU2 MCP tools/list failed: {tools_list['error']}")

        tool_names = [
            tool["name"]
            for tool in tools_list["result"]["tools"]
            if isinstance(tool, dict) and isinstance(tool.get("name"), str)
        ]
        if "run_su2_cfd" not in tool_names:
            raise ValueError(
                f"Expected the served tool list to include 'run_su2_cfd'; got {tool_names!r}."
            )

        # Use `-h` as a cheap, deterministic smoke test that still exercises
        # the real wrapped CLI entry point.
        server.stdin.write(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"arguments": {"extra_argv": ["-h"]}, "name": "run_su2_cfd"},
                }
            )
            + "\n"
        )
        server.stdin.flush()
        tool_call = json.loads(server.stdout.readline())
        if "error" in tool_call:
            raise RuntimeError(f"SU2 MCP tools/call failed: {tool_call['error']}")
    finally:
        # Closing stdin allows the stdio server to notice end-of-session and exit.
        if not server.stdin.closed:
            server.stdin.close()
        try:
            return_code = server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            # Kill hung servers so the example does not block indefinitely.
            server.kill()
            return_code = server.wait(timeout=5)
        server_stderr = server.stderr.read()

    # Report server stderr verbatim to keep the wrapped command behavior
    # inspectable when something goes wrong.
    if return_code != 0:
        raise RuntimeError(
            f"SU2 MCP server exited with code {return_code}.\nstderr:\n{server_stderr}"
        )

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

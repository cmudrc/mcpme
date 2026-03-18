"""Case study for ingesting, serving, and then using the SU2 CLI wrapper.

## Introduction

This case study models the shape of a real heavyweight CLI integration more
closely than the smaller examples: first ingest the upstream surface into a
generated facade, persist that generated artifact, serve it over stdio MCP,
and only then use it through a client request. The split is deliberate so
contributors can inspect the generated wrapper before the wrapped command is
executed.

## Preset Environment

The checked-in command surface for this case study lives under
`case_studies/support/su2_cli/commands/`. Run `case_studies/su2_cli/ingest.py`
to scaffold and persist the facade under `artifacts/case_studies/su2_cli/`,
`case_studies/su2_cli/serve.py` to expose that persisted facade as an MCP
server, and `case_studies/su2_cli/use.py` to hit that MCP server and exercise
the wrapped CLI.

## Technical Implementation

- `ingest.py` probes for `SU2_CFD`, runs the public scaffold CLI through the
  checked-in shell wrapper, and writes `ingest_state.json` under the case-study
  artifact directory.
- `serve.py` loads the saved generated facade through the public API and serves
  it over stdio with `mcpme.serve_stdio`.
- `use.py` reads the persisted ingest state, starts `serve.py` as a
  subprocess, sends `initialize`, `tools/list`, and `tools/call` requests, and
  captures the JSON-RPC responses.
- The result payload retains both the scaffold report and the wrapped help-path
  execution evidence returned by the served MCP runtime.

## Expected Results

When SU2 is available, `ingest.py` prints a `passed` payload with the scaffold
report, `serve.py` can expose the persisted facade over stdio MCP, and
`use.py` prints a `passed` payload with the served tool names and the wrapped
help-path result. On machines without SU2 installed, the ingest step persists
a `skipped_unavailable` state and the use step reports the same skip reason
without failing.

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
import os
import subprocess
import sys
from pathlib import Path

CASE_STUDY_ID = "su2_cli"
REPO_ROOT = Path(__file__).resolve().parents[2]
SERVE_PATH = REPO_ROOT / "case_studies" / CASE_STUDY_ID / "serve.py"
STATE_PATH = REPO_ROOT / "artifacts" / "case_studies" / CASE_STUDY_ID / "ingest_state.json"


def main() -> None:
    """Hit the served SU2 MCP runtime and print the stable JSON payload."""
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

    env = dict(os.environ)
    pythonpath_entries = [str((REPO_ROOT / "src").resolve())]
    if env.get("PYTHONPATH"):
        pythonpath_entries.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(pythonpath_entries)

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
        raise RuntimeError("Expected stdio pipes when launching the SU2 case-study MCP server.")

    try:
        server.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"}) + "\n")
        server.stdin.flush()
        initialize = json.loads(server.stdout.readline())
        if "error" in initialize:
            raise RuntimeError(f"SU2 MCP initialize failed: {initialize['error']}")

        server.stdin.write(
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
        )
        server.stdin.flush()

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
        if not server.stdin.closed:
            server.stdin.close()
        try:
            return_code = server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            return_code = server.wait(timeout=5)
        server_stderr = server.stderr.read()

    if return_code != 0:
        raise RuntimeError(
            f"SU2 MCP server exited with code {return_code}.\nstderr:\n{server_stderr}"
        )

    tool_result = tool_call["result"]
    if "SU2_CFD" not in json.dumps(tool_result, sort_keys=True):
        raise ValueError("Expected the wrapped SU2 help output to mention 'SU2_CFD'.")

    payload = {
        "case_study": CASE_STUDY_ID,
        "ingest_state": {
            "generated_facade": ingest_state["generated_facade"],
            "state_path": str(STATE_PATH),
        },
        "mcp_session": {
            "server_info": initialize["result"]["serverInfo"],
            "tool_names": tool_names,
        },
        "phase": "use",
        "report": ingest_state["report"],
        "result": {"run_su2_cfd": tool_result},
        "status": "passed",
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

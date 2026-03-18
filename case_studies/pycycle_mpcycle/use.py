"""Case study for ingesting, serving, and then using pyCycle `MPCycle`.

## Introduction

This case study shows how `mcpme` can carve a useful session-oriented wrapper
out of a real engineering Python package without teaching the library
anything pyCycle-specific. The workflow mirrors a more realistic integration
path: ingest the package once, persist the generated facade, serve that facade
over stdio MCP, and then drive the wrapped session lifecycle through MCP.

## Preset Environment

The case-study-specific public scaffold command is checked in under
`case_studies/support/pycycle_mpcycle/commands/`. Run
`case_studies/pycycle_mpcycle/ingest.py` first to generate and persist the
facade under `artifacts/case_studies/pycycle_mpcycle/`,
`case_studies/pycycle_mpcycle/serve.py` to expose that persisted facade over
stdio MCP, and `case_studies/pycycle_mpcycle/use.py` to hit that MCP server
and exercise the generated tools.

## Technical Implementation

- `ingest.py` requires `import pycycle.api` to succeed so the case study only
  runs against the engineering `om-pycycle` distribution.
- The ingest step runs the public scaffold CLI through a checked-in shell
  wrapper and persists the discovered tool names for the `MPCycle` lifecycle.
- `serve.py` loads the saved generated facade through the public API and serves
  it over stdio with `mcpme.serve_stdio`.
- `use.py` starts `serve.py`, sends `initialize`, `tools/list`, and
  `tools/call` requests, then exercises the create/add-parameter/close
  lifecycle entirely through the served MCP interface.

## Expected Results

When the engineering pyCycle package is available, `ingest.py` prints a
`passed` payload with the scaffold report and persisted tool names, `serve.py`
can expose the persisted facade over stdio MCP, and `use.py` prints a
`passed` payload with the session lifecycle outputs. On machines without
`pycycle.api`, the ingest step persists a `skipped_unavailable` state and the
use step reports the same skip reason without failing.

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

import json
import os
import subprocess
import sys
from pathlib import Path

CASE_STUDY_ID = "pycycle_mpcycle"
REPO_ROOT = Path(__file__).resolve().parents[2]
SERVE_PATH = REPO_ROOT / "case_studies" / CASE_STUDY_ID / "serve.py"
STATE_PATH = REPO_ROOT / "artifacts" / "case_studies" / CASE_STUDY_ID / "ingest_state.json"


def main() -> None:
    """Hit the served pyCycle MCP runtime and print the stable JSON payload."""
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
        raise RuntimeError("Expected stdio pipes when launching the pyCycle case-study MCP server.")

    try:
        server.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"}) + "\n")
        server.stdin.flush()
        initialize = json.loads(server.stdout.readline())
        if "error" in initialize:
            raise RuntimeError(f"pyCycle MCP initialize failed: {initialize['error']}")

        server.stdin.write(
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
        )
        server.stdin.flush()

        server.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}) + "\n")
        server.stdin.flush()
        tools_list = json.loads(server.stdout.readline())
        if "error" in tools_list:
            raise RuntimeError(f"pyCycle MCP tools/list failed: {tools_list['error']}")

        tool_names = [
            tool["name"]
            for tool in tools_list["result"]["tools"]
            if isinstance(tool, dict) and isinstance(tool.get("name"), str)
        ]
        for expected_name in ingest_state["tool_names"].values():
            if expected_name not in tool_names:
                raise ValueError(
                    "Expected the served tool list to include "
                    f"{expected_name!r}; got {tool_names!r}."
                )

        server.stdin.write(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"arguments": {}, "name": ingest_state["tool_names"]["create"]},
                }
            )
            + "\n"
        )
        server.stdin.flush()
        create_call = json.loads(server.stdout.readline())
        if "error" in create_call:
            raise RuntimeError(f"pyCycle MCP create call failed: {create_call['error']}")
        create_record = json.loads(create_call["result"]["content"][0]["text"])
        session_id = create_record["session_id"]

        server.stdin.write(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "tools/call",
                    "params": {
                        "arguments": {"name": "FAR", "session_id": session_id, "val": 0.02},
                        "name": ingest_state["tool_names"]["add_cycle_param"],
                    },
                }
            )
            + "\n"
        )
        server.stdin.flush()
        add_param_call = json.loads(server.stdout.readline())
        if "error" in add_param_call:
            raise RuntimeError(
                f"pyCycle MCP add-cycle-param call failed: {add_param_call['error']}"
            )
        add_param_record = json.loads(add_param_call["result"]["content"][0]["text"])

        server.stdin.write(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 5,
                    "method": "tools/call",
                    "params": {
                        "arguments": {"session_id": session_id},
                        "name": ingest_state["tool_names"]["close"],
                    },
                }
            )
            + "\n"
        )
        server.stdin.flush()
        close_call = json.loads(server.stdout.readline())
        if "error" in close_call:
            raise RuntimeError(f"pyCycle MCP close call failed: {close_call['error']}")
        close_record = json.loads(close_call["result"]["content"][0]["text"])
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
            f"pyCycle MCP server exited with code {return_code}.\nstderr:\n{server_stderr}"
        )

    if close_record.get("success") is not True:
        raise ValueError("Expected the served close wrapper to report success.")

    payload = {
        "case_study": CASE_STUDY_ID,
        "ingest_state": {
            "generated_facade": ingest_state["generated_facade"],
            "state_path": str(STATE_PATH),
            "tool_names": ingest_state["tool_names"],
        },
        "mcp_session": {
            "server_info": initialize["result"]["serverInfo"],
            "tool_names": tool_names,
        },
        "phase": "use",
        "report": ingest_state["report"],
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

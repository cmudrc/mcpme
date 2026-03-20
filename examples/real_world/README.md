# Real-World Examples

The real-world examples in `mcpcraft` are intentionally separate from the
small, always-runnable `examples/` contract.

Each real-world example:

- uses only the public `mcpcraft` surface plus the public scaffold CLI,
- targets a real engineering upstream or CLI shape,
- stays self-contained and reproducible from the repository root, and
- reports either `passed` or `skipped_unavailable` as stable JSON.

Each example lives in its own directory with three companion scripts:

- `ingest.py` performs the one-shot scaffold step and writes the standard
  artifact pair: `generated_facade.py` and `scaffold_report.json`.
- `serve.py` loads that saved generated facade and serves it over stdio MCP.
- `use.py` demonstrates the ingested capability through MCP requests against
  the saved facade without launching `serve.py`.

Checked-in support inputs live under `examples/support/real_world/<example_id>/`,
while generated facades and execution artifacts belong under
`artifacts/examples/real_world/<example_id>/`.

Included real-world examples:

- `su2_cli/`: ingest and then use a command facade around `SU2_CFD -h`.
- `pycycle_mpcycle/`: ingest and then use a package facade around `pycycle.api.MPCycle`.
- `tigl_cpacs/`: ingest and then use a package facade around a tiny TiGL/TiXI helper package.

Run one real-world example manually with the ingest-then-use flow:

```bash
PYTHONPATH=src python examples/real_world/pycycle_mpcycle/ingest.py
PYTHONPATH=src python examples/real_world/pycycle_mpcycle/use.py
```

Inspect the stdio server separately when you want to demo the served facade:

```bash
PYTHONPATH=src python examples/real_world/pycycle_mpcycle/serve.py
```

`serve.py` and `use.py` are intentionally separate. `serve.py` exposes the
saved facade over stdio MCP, while `use.py` exercises that same saved facade
through in-process MCP requests.

Or use the convenience targets:

```bash
make run-real-world-examples
make run-real-world-example CASE=pycycle_mpcycle
```

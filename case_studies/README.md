# Case Studies

The case studies in `mcpme` are intentionally separate from the small,
always-runnable `examples/` contract.

Each case study:

- uses only the public `mcpme` surface plus the public scaffold CLI,
- targets a real engineering upstream or CLI shape,
- stays self-contained and reproducible from the repository root, and
- reports either `passed` or `skipped_unavailable` as stable JSON.

Each case lives in its own directory with three companion scripts:

- `ingest.py` performs the one-shot scaffold step and persists `ingest_state.json`.
- `serve.py` loads that persisted facade and serves it over stdio MCP.
- `use.py` starts the served MCP and demonstrates the ingested capability
  through client requests instead of calling the manifest directly.

Checked-in support inputs live under `case_studies/support/<case_id>/`, while
generated facades and execution artifacts belong under
`artifacts/case_studies/<case_id>/`.

Included case studies:

- `su2_cli/`: ingest and then use a command facade around `SU2_CFD -h`.
- `pycycle_mpcycle/`: ingest and then use a package facade around `pycycle.api.MPCycle`.
- `tigl_cpacs/`: ingest and then use a package facade around a tiny TiGL/TiXI helper package.

Run one case study manually with the real ingest-then-use flow:

```bash
PYTHONPATH=src python case_studies/pycycle_mpcycle/ingest.py
PYTHONPATH=src python case_studies/pycycle_mpcycle/use.py
```

`use.py` starts `serve.py` automatically. Run `serve.py` directly only when you
want to inspect the served MCP endpoint yourself.

Or use the convenience targets:

```bash
make run-case-studies
make run-case-study CASE=pycycle_mpcycle
```

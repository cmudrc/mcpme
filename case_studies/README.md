# Case Studies

The case studies in `mcpwrap` are intentionally separate from the small,
always-runnable `examples/` contract.

Each case study:

- uses only the public `mcpwrap` surface plus the public scaffold CLI,
- targets a real engineering upstream or CLI shape,
- stays self-contained and reproducible from the repository root, and
- reports either `passed` or `skipped_unavailable` as stable JSON.

Each case lives in its own directory with three companion scripts:

- `ingest.py` performs the one-shot scaffold step and writes the standard
  artifact pair: `generated_facade.py` and `scaffold_report.json`.
- `serve.py` loads that saved generated facade and serves it over stdio MCP.
- `use.py` demonstrates the ingested capability through MCP requests against
  the saved facade without launching `serve.py`.

Checked-in support inputs live under `case_studies/support/<case_id>/`, while
generated facades and execution artifacts belong under
`artifacts/case_studies/<case_id>/`.

Included case studies:

- `su2_cli/`: ingest and then use a command facade around `SU2_CFD -h`.
- `pycycle_mpcycle/`: ingest and then use a package facade around `pycycle.api.MPCycle`.
- `tigl_cpacs/`: ingest and then use a package facade around a tiny TiGL/TiXI helper package.

Run one case study manually with the ingest-then-use flow:

```bash
PYTHONPATH=src python case_studies/pycycle_mpcycle/ingest.py
PYTHONPATH=src python case_studies/pycycle_mpcycle/use.py
```

Inspect the stdio server separately when you want to demo the served facade:

```bash
PYTHONPATH=src python case_studies/pycycle_mpcycle/serve.py
```

`serve.py` and `use.py` are intentionally separate. `serve.py` exposes the
saved facade over stdio MCP, while `use.py` exercises that same saved facade
through in-process MCP requests.

Or use the convenience targets:

```bash
make run-case-studies
make run-case-study CASE=pycycle_mpcycle
```

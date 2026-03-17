# Case Studies

The case studies in `mcpme` are intentionally separate from the small,
always-runnable `examples/` contract.

Each case study:

- uses only the public `mcpme` surface plus the public scaffold CLI,
- targets a real engineering upstream or CLI shape,
- stays self-contained and reproducible from the repository root, and
- reports either `passed` or `skipped_unavailable` as stable JSON.

Checked-in support inputs live under `case_studies/support/<case_id>/`, while
generated facades and execution artifacts belong under
`artifacts/case_studies/<case_id>/`.

Included case studies:

- `su2_cli.py`: one-shot command scaffolding around `SU2_CFD -h`.
- `pycycle_mpcycle.py`: one-shot package scaffolding around `pycycle.api.MPCycle`.
- `tigl_cpacs.py`: one-shot package scaffolding around a tiny TiGL/TiXI helper package.

Run them locally with:

```bash
PYTHONPATH=src python case_studies/su2_cli.py
PYTHONPATH=src python case_studies/pycycle_mpcycle.py
PYTHONPATH=src python case_studies/tigl_cpacs.py
```

Or use the convenience targets:

```bash
make run-case-studies
make run-case-study CASE=pycycle_mpcycle
```

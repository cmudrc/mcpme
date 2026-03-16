# Live Raw-Upstream Challenges

This directory holds a live integration track for `mcpme` that is intentionally
separate from the public examples and API documentation contract.

The challenge suite exists to answer a blunt question:

Can `mcpme` ingest and wrap real upstream engineering tools without hand-built
adapter code?

## Ground Rules

- Challenges are live and raw upstream only.
- Challenge fixtures may provide tiny input files, but the wrapped target must
  be the real upstream package or command.
- The reduced `gha_subset` tier is designed to run on GitHub-hosted runners.
- The `local_full` tier is broader and may include currently failing cases to
  keep pressure on missing capability.
- Challenge failures are informative and non-gating. Harness failures are not.

## Layout

- `catalog/`: one TOML file per challenge
- `fixtures/`: tiny deterministic inputs used by challenge smoke steps

## Running

Run the reduced CI subset locally:

```bash
make challenges-subset
```

Run the broader local suite:

```bash
make challenges-full
```

Regenerate the reduced live badge from metrics:

```bash
make challenges-metrics
```

## Template Variables

Challenge catalog fields may use simple `{name}` templates. The harness exposes
these keys:

- `repo_root`
- `challenge_root`
- `challenge_artifact_dir`
- `challenge_fixture_dir`
- `python_executable`
- `venv_bin_dir`
- `pathsep`
- `env_PATH`

Smoke steps can also capture JSON values from earlier steps and reuse them as
later template variables.

"""Runnable example for source-first Python callable discovery.

## Introduction

This example shows the simplest useful `mcpme` workflow: expose a typed Python
callable as an MCP tool without any handwritten server boilerplate.

The wrapped function models a small engineering post-processing helper. It is
already trusted and deterministic, so the wrapper layer focuses on harvesting
its public interface and preserving its execution contract.

## Technical Implementation

- Import only the curated top-level public API from `mcpme`.
- Define a typed callable with a Google-style docstring and an `MCP:` block.
- Build a :class:`mcpme.Manifest` directly from that callable.
- Print the manifest as JSON so the generated tool surface is easy to inspect.

## Expected Results

Running this script prints a JSON manifest with one tool named
`summarize_mesh`. The tool description, input schema, output schema, and MCP
annotations all come from deterministic parsing of the callable and its
docstring.

## References

- ``README.md``
- ``docs/specification.rst``
- ``docs/api.rst``
"""

from __future__ import annotations

import json

from mcpme import Manifest, build_manifest


def summarize_mesh(job_name: str, iterations: int = 3) -> dict[str, int | str]:
    """Summarize a deterministic meshing job.

    Args:
        job_name: Job label used for the mesh run.
        iterations: Refinement iteration count.

    Returns:
        A lightweight job summary.

    MCP:
        title: Summarize Mesh
        read_only: true
        idempotent: true
    """
    return {"job_name": job_name, "iterations": iterations}


def build_example_manifest() -> Manifest:
    """Build the manifest used by this example."""
    return build_manifest(targets=[summarize_mesh])


def main() -> None:
    """Print the generated manifest for a registered Python callable."""
    manifest = build_example_manifest()
    print(json.dumps(manifest.to_dict(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

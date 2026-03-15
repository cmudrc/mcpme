"""Command-line entry points for deterministic wrapper workflows."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from .discovery import build_manifest
from .runtime import serve_stdio


def main(argv: Sequence[str] | None = None) -> int:
    """Run the ``mcpme`` command-line interface."""
    parser = argparse.ArgumentParser(description="Deterministic engineering tool wrappers for MCP.")
    parser.add_argument("--config", type=Path, help="Optional configuration path.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    manifest_parser = subparsers.add_parser("manifest", help="Emit the generated manifest as JSON.")
    manifest_parser.add_argument("targets", nargs="*", help="Optional explicit targets.")

    inspect_parser = subparsers.add_parser(
        "inspect",
        help="List generated tool names and descriptions.",
    )
    inspect_parser.add_argument("targets", nargs="*", help="Optional explicit targets.")

    serve_parser = subparsers.add_parser("serve", help="Serve the generated manifest over stdio.")
    serve_parser.add_argument("targets", nargs="*", help="Optional explicit targets.")

    args = parser.parse_args(argv)
    explicit_targets = [
        Path(target) if Path(target).exists() else target for target in getattr(args, "targets", ())
    ]
    manifest = build_manifest(
        targets=explicit_targets,
        config_path=args.config,
    )
    if args.command == "manifest":
        print(json.dumps(manifest.to_dict(), indent=2, sort_keys=True))
        return 0
    if args.command == "inspect":
        for tool in manifest.tools:
            print(f"{tool.name}: {tool.description}")
        return 0
    serve_stdio(manifest)
    return 0

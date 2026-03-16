"""Command-line entry points for deterministic wrapper workflows."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from ._openapi import scaffold_openapi
from ._scaffold import scaffold_command, scaffold_package
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

    scaffold_package_parser = subparsers.add_parser(
        "scaffold-package",
        help="Generate an inspectable Python facade for an installed package.",
    )
    scaffold_package_parser.add_argument("package_name", help="Importable package or module name.")
    scaffold_package_parser.add_argument("output", type=Path, help="Generated Python facade path.")
    scaffold_package_parser.add_argument(
        "--include-submodules",
        action="store_true",
        help="Inspect public submodules below the root package.",
    )
    scaffold_package_parser.add_argument(
        "--max-modules",
        type=int,
        help="Optional cap on the number of imported modules to inspect.",
    )
    scaffold_package_parser.add_argument(
        "--max-generated-tools",
        type=int,
        help="Optional cap on the number of generated wrapper tools.",
    )
    scaffold_package_parser.add_argument(
        "--module-include",
        action="append",
        default=[],
        help="Regex for module names that should be included.",
    )
    scaffold_package_parser.add_argument(
        "--module-exclude",
        action="append",
        default=[],
        help="Regex for module names that should be excluded.",
    )
    scaffold_package_parser.add_argument(
        "--symbol-include",
        action="append",
        default=[],
        help="Regex for symbol names that should be included.",
    )
    scaffold_package_parser.add_argument(
        "--symbol-exclude",
        action="append",
        default=[],
        help="Regex for symbol names that should be excluded.",
    )
    scaffold_package_parser.add_argument(
        "--allow-reexports",
        action="store_true",
        help="Keep symbols re-exported from outside the target namespace.",
    )

    scaffold_command_parser = subparsers.add_parser(
        "scaffold-command",
        help="Generate an inspectable Python facade for a CLI command.",
    )
    scaffold_command_parser.add_argument("output", type=Path, help="Generated Python facade path.")
    scaffold_command_parser.add_argument(
        "--name",
        help="Optional generated function name. Defaults to run_<command>.",
    )
    scaffold_command_parser.add_argument(
        "--help-timeout-seconds",
        type=float,
        default=5.0,
        help="Timeout for capturing command help text.",
    )
    scaffold_command_parser.add_argument(
        "--help-probe-arg",
        action="append",
        default=[],
        help="Argument appended when probing command help. Repeat to provide multiple tokens.",
    )
    scaffold_command_parser.add_argument(
        "command_tokens",
        nargs="+",
        help="Command to wrap. Prefix with -- to separate it from CLI options.",
    )

    scaffold_openapi_parser = subparsers.add_parser(
        "scaffold-openapi",
        help="Generate an inspectable Python facade from an OpenAPI spec.",
    )
    scaffold_openapi_parser.add_argument("spec_path", type=Path, help="OpenAPI JSON or YAML file.")
    scaffold_openapi_parser.add_argument("output", type=Path, help="Generated Python facade path.")
    scaffold_openapi_parser.add_argument(
        "--base-url",
        help="Optional base URL override when the spec server URL is missing or templated.",
    )

    args = parser.parse_args(argv)
    if args.command == "scaffold-package":
        report = scaffold_package(
            args.package_name,
            args.output,
            include_submodules=args.include_submodules,
            max_modules=args.max_modules,
            max_generated_tools=args.max_generated_tools,
            module_include_patterns=tuple(args.module_include),
            module_exclude_patterns=tuple(args.module_exclude),
            symbol_include_patterns=tuple(args.symbol_include),
            symbol_exclude_patterns=tuple(args.symbol_exclude),
            allow_reexports=args.allow_reexports,
        )
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
        return 0
    if args.command == "scaffold-command":
        report = scaffold_command(
            tuple(args.command_tokens),
            args.output,
            function_name=args.name,
            help_timeout_seconds=args.help_timeout_seconds,
            help_probe_args=tuple(args.help_probe_arg or ["--help"]),
        )
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
        return 0
    if args.command == "scaffold-openapi":
        report = scaffold_openapi(
            args.spec_path,
            args.output,
            base_url=args.base_url,
        )
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
        return 0

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


if __name__ == "__main__":
    raise SystemExit(main())

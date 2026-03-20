"""Tests for discovery edge paths and deterministic overrides."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from mcpcraft import ArgparseCommand, build_manifest
from mcpcraft.config import ToolOverride
from mcpcraft.discovery import (
    _apply_override,
    _build_python_tool_manifest,
    _load_module_from_path,
    _public_names_from_python_file,
)
from mcpcraft.manifest import SourceReference, ToolAnnotations


def helper_tool(job_name: str) -> str:
    """Echo a job name.

    :param job_name: Job label.
    :returns: Same job label.
    """

    return job_name


def test_discovery_handles_callable_directory_and_module_edge_cases(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    """Direct callables, directories, modules, and cached file imports should work."""

    manifest = build_manifest(targets=[helper_tool])
    assert manifest.tool_names == ("helper_tool",)

    tools_dir = tmp_path / "tool_dir"
    tools_dir.mkdir()
    (tools_dir / "__init__.py").write_text('"""Ignored package marker."""\n', encoding="utf-8")
    (tools_dir / "dir_tool.py").write_text(
        """__all__ = ["IGNORED", "run_dir"]\n"""
        """IGNORED = 3\n\n"""
        """def run_dir(job_name: str) -> str:\n"""
        '''    """Run from a directory.\n\n'''
        """    :param job_name: Job label.\n"""
        """    :returns: Same job label.\n"""
        '''    """\n'''
        """    return job_name\n""",
        encoding="utf-8",
    )
    directory_manifest = build_manifest(targets=[tools_dir])
    assert directory_manifest.tool_names == ("run_dir",)

    module_dir = tmp_path / "pkg_case"
    module_dir.mkdir()
    (module_dir / "__init__.py").write_text(
        """__all__ = ["VALUE", "run_module"]\n"""
        """VALUE = 1\n\n"""
        """def run_module(job_name: str) -> str:\n"""
        '''    """Run from a module.\n\n'''
        """    :param job_name: Job label.\n"""
        """    :returns: Same job label.\n"""
        '''    """\n'''
        """    return job_name\n""",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    module_manifest = build_manifest(targets=["pkg_case"])
    assert module_manifest.tool_names == ("run_module",)

    invalid_all = tmp_path / "invalid_all.py"
    invalid_all.write_text(
        "__all__ = [UNKNOWN]\n"
        "def alpha(value: str) -> str:\n"
        '    """Alpha.\n\n:param value: Input text.\n:returns: Same text.\n    """\n'
        "    return value\n",
        encoding="utf-8",
    )
    assert _public_names_from_python_file(invalid_all) == ("alpha",)
    valid_module = _load_module_from_path(tools_dir / "dir_tool.py")
    assert valid_module is _load_module_from_path(tools_dir / "dir_tool.py")


def test_source_discovery_avoids_import_side_effects_and_resolves_reexports(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    """Source-backed discovery should not import files and should follow re-exports."""

    side_effect = tmp_path / "side_effect.py"
    side_effect.write_text(
        "raise RuntimeError('discovery imported user code')\n\n"
        "def safe_run(job_name: str) -> str:\n"
        '    """Safely discovered.\n\n'
        "    :param job_name: Job label.\n"
        "    :returns: Same job label.\n"
        '    """\n'
        "    return job_name\n",
        encoding="utf-8",
    )
    manifest = build_manifest(targets=[side_effect])
    assert manifest.tool_names == ("safe_run",)

    package_dir = tmp_path / "reexport_pkg"
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text(
        '__all__ = ["solve"]\nfrom .solver import run_solver as solve\n',
        encoding="utf-8",
    )
    (package_dir / "solver.py").write_text(
        "def run_solver(job_name: str) -> str:\n"
        '    """Run through a re-export.\n\n'
        "    :param job_name: Job label.\n"
        "    :returns: Same job label.\n"
        '    """\n'
        "    return job_name.upper()\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    package_manifest = build_manifest(targets=["reexport_pkg"])
    assert package_manifest.tool_names == ("solve",)


def test_discovery_rejects_hidden_or_unsupported_python_signatures() -> None:
    """Unsupported call signatures and hidden tools should fail explicitly."""

    def positional_only(value: str, /) -> str:
        """Reject positional-only parameters."""

        return value

    def keyword_rest(**kwargs: str) -> dict[str, str]:
        """Reject keyword splats."""

        return kwargs

    def hidden_tool(value: str) -> str:
        """Hide this tool.

        :param value: Input text.
        :returns: Same text.

        MCP:
            hidden: true
        """

        return value

    with pytest.raises(ValueError):
        _build_python_tool_manifest(
            positional_only,
            SourceReference(kind="callable", target="positional_only"),
        )
    with pytest.raises(ValueError):
        _build_python_tool_manifest(
            keyword_rest,
            SourceReference(kind="callable", target="keyword_rest"),
        )
    with pytest.raises(ValueError):
        _build_python_tool_manifest(
            hidden_tool,
            SourceReference(kind="callable", target="hidden_tool"),
        )


def test_discovery_supports_argparse_overrides_and_duplicate_namespacing(
    tmp_path: Path,
) -> None:
    """Argparse targets, overrides, and duplicate names should stay deterministic."""

    parser = argparse.ArgumentParser(description="Run the parser tool.")
    parser.add_argument("job_name")
    parser.add_argument("--cache", action="store_false", help="Disable cache.")
    parser.add_argument("--level", choices=[1, 2], default=1, help="Discrete level.")
    parser.add_argument("--samples", nargs="+", type=float, help="Sample values.")

    manifest = build_manifest(
        targets=[
            ArgparseCommand(
                name="parser_tool",
                parser=parser,
                command=("python", "tool.py"),
            )
        ],
        artifact_root=tmp_path / "artifacts",
    )
    tool = manifest.get_tool("parser_tool")
    assert tool.input_schema["properties"]["cache"]["type"] == "boolean"
    assert tool.input_schema["properties"]["level"]["enum"] == [1, 2]
    assert tool.input_schema["properties"]["samples"]["type"] == "array"

    overridden_tool, _ = _apply_override(
        (tool, manifest.get_binding("parser_tool")),
        ToolOverride(
            title="Parser Tool",
            description="Overridden description.",
            annotations=ToolAnnotations(read_only=True),
        ),
    )
    assert overridden_tool.title == "Parser Tool"
    assert overridden_tool.description == "Overridden description."
    assert overridden_tool.annotations.read_only is True

    duplicate_manifest = build_manifest(targets=[helper_tool, helper_tool])
    assert duplicate_manifest.tool_names == (
        "helper_tool__helper_tool",
        "test_discovery_edges_helper_tool__helper_tool",
    )

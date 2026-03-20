"""Tests for deterministic manifest generation."""

from __future__ import annotations

from pathlib import Path

from mcpcraft import build_manifest


def test_build_manifest_from_python_file_generates_schema(tmp_path: Path) -> None:
    """Public functions with type hints should become MCP tool manifests."""

    source = tmp_path / "mesh_tools.py"
    source.write_text(
        '''"""Mesh utilities."""\n\n'''
        "def mesh_model(input_path: str, iterations: int = 3) -> dict[str, int]:\n"
        '    """Generate a mesh.\n\n'
        "    :param input_path: Path to the CAD file.\n"
        "    :param iterations: Number of refinement iterations.\n"
        "    :returns: A summary containing the element count.\n\n"
        "    MCP:\n"
        "        title: Mesh CAD Model\n"
        "        read_only: false\n"
        "        idempotent: true\n"
        '    """\n'
        '    return {"elements": iterations}\n',
        encoding="utf-8",
    )

    manifest = build_manifest(targets=[source])
    tool = manifest.get_tool("mesh_model")

    assert manifest.tool_names == ("mesh_model",)
    assert tool.title == "Mesh CAD Model"
    assert tool.annotations.read_only is False
    assert tool.annotations.idempotent is True
    assert tool.input_schema["required"] == ["input_path"]
    assert tool.input_schema["properties"]["iterations"]["default"] == 3
    assert tool.output_schema == {
        "type": "object",
        "additionalProperties": {"type": "integer"},
    }


def test_build_manifest_respects_module_all_order(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    """The module's declared public order should be preserved."""

    package_dir = tmp_path / "sample_pkg"
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text(
        """__all__ = ["beta_tool", "alpha_tool"]\n"""
        """def alpha_tool(value: str) -> str:\n"""
        '''    """Alpha tool.\n\n'''
        """    :param value: Input text.\n"""
        """    :returns: Echoed text.\n"""
        '''    """\n'''
        """    return value\n\n"""
        """def beta_tool(count: int) -> int:\n"""
        '''    """Beta tool.\n\n'''
        """    :param count: Count value.\n"""
        """    :returns: The same count.\n"""
        '''    """\n'''
        """    return count\n""",
        encoding="utf-8",
    )

    monkeypatch.syspath_prepend(str(tmp_path))
    manifest = build_manifest(targets=["sample_pkg"])

    assert manifest.tool_names == ("beta_tool", "alpha_tool")

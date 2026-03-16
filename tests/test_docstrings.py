"""Tests for deterministic docstring parsing."""

from __future__ import annotations

from mcpme.docstrings import parse_docstring


def test_parse_docstring_extracts_sphinx_sections() -> None:
    """Sphinx field lists should map to deterministic metadata."""

    parsed = parse_docstring(
        """
        Generate a finite-element mesh.

        :param input_path: Path to the CAD file.
        :param target_size_mm: Desired global element size.
        :returns: A summary containing the mesh path.

        MCP:
            title: Mesh CAD Model
            read_only: false
            idempotent: true
        """
    )

    assert parsed.summary == "Generate a finite-element mesh."
    assert parsed.param_descriptions == {
        "input_path": "Path to the CAD file.",
        "target_size_mm": "Desired global element size.",
    }
    assert parsed.returns_description == "A summary containing the mesh path."
    assert parsed.mcp_metadata == {
        "title": "Mesh CAD Model",
        "read_only": False,
        "idempotent": True,
    }


def test_parse_docstring_does_not_parse_legacy_section_blocks() -> None:
    """Legacy section headers should no longer be treated as structured fields."""

    parsed = parse_docstring(
        """
        Legacy shape.

        Args:
            deck: Input deck.

        Returns:
            Output deck.
        """
    )

    assert parsed.summary == "Legacy shape. Args: deck: Input deck. Returns: Output deck."
    assert parsed.param_descriptions == {}
    assert parsed.returns_description is None

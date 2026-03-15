"""Tests for deterministic docstring parsing."""

from __future__ import annotations

from mcpme.docstrings import parse_google_docstring


def test_parse_google_docstring_extracts_sections() -> None:
    """Google-style sections should map to deterministic metadata."""

    parsed = parse_google_docstring(
        """
        Generate a finite-element mesh.

        Args:
            input_path: Path to the CAD file.
            target_size_mm: Desired global element size.

        Returns:
            A summary containing the mesh path.

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

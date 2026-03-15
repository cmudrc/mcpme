"""Tests for the curated public API."""

from __future__ import annotations

import mcpme as package


def test_public_exports_match_the_curated_api() -> None:
    """Keep the top-level exports explicit and stable."""

    assert package.__all__ == [
        "ArgparseCommand",
        "Manifest",
        "McpServer",
        "ToolExecutionResult",
        "build_manifest",
        "execute_tool",
        "serve_stdio",
    ]

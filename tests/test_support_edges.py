"""Tests for docstring, config, manifest, and schema edge paths."""

from __future__ import annotations

from pathlib import Path

import pytest

from mcpme.config import _optional_bool, load_config
from mcpme.docstrings import parse_google_docstring
from mcpme.manifest import (
    ArgparseOptionSpec,
    FileTemplate,
    Manifest,
    SourceReference,
    SubprocessResultSpec,
    ToolAnnotations,
    ToolManifest,
)
from mcpme.schema import SchemaValidationError, coerce_value, to_json_compatible, validate_value


def test_docstring_and_config_edge_paths_are_explicit(tmp_path: Path) -> None:
    """Empty docstrings, continuations, bad metadata, and missing config should be handled."""

    parsed = parse_google_docstring(
        """
        Summarize a run.

        Args:
            config: Initial line.
                Continued detail.

        Returns:

        MCP:
            read_only: false
            note without colon
        """
    )
    assert parse_google_docstring(None).summary == ""
    assert parsed.param_descriptions["config"] == "Initial line. Continued detail."
    assert parsed.returns_description is None
    assert parsed.mcp_metadata["read_only"] is False

    with pytest.raises(ValueError):
        parse_google_docstring(
            """
            Bad metadata.

            MCP:
                unsupported: value
            """
        )

    with pytest.raises(ValueError):
        _optional_bool("yes")

    missing_config = load_config(tmp_path / "does-not-exist.toml")
    assert missing_config.targets == ()


def test_manifest_and_validation_helpers_cover_remaining_paths() -> None:
    """Manifest serialization and validation errors should remain deterministic."""

    tool = ToolManifest(
        name="tool",
        title="Tool",
        description="Describe tool.",
        input_schema={"type": "object", "properties": {}},
        output_schema={"type": "object", "properties": {}},
        annotations=ToolAnnotations(read_only=True),
        source=SourceReference(kind="module", target="pkg.tool", location="pkg.tool.fn"),
        binding_kind="python",
    )
    manifest = Manifest(
        tools=(tool,),
        runtime_bindings={
            "tool": ArgparseOptionSpec("job", ("--job",), False, True, None, "store")
        },
    )

    assert tool.to_dict()["title"] == "Tool"
    assert tool.to_mcp_tool()["annotations"]["readOnlyHint"] is True
    assert FileTemplate(path="input.txt", template="{value}").to_dict()["path"] == "input.txt"
    assert (
        SubprocessResultSpec(kind="file_json", path="result.json").to_dict()["path"]
        == "result.json"
    )
    assert manifest.to_dict()["tools"][0]["name"] == "tool"
    assert manifest.get_binding("tool").dest == "job"

    with pytest.raises(KeyError):
        manifest.get_tool("missing")

    with pytest.raises(SchemaValidationError):
        validate_value("bad", {"anyOf": [{"type": "integer"}, {"type": "boolean"}]})
    with pytest.raises(SchemaValidationError):
        validate_value("bad", {"type": "null"})
    with pytest.raises(SchemaValidationError):
        validate_value("bad", {"type": "array", "items": {"type": "integer"}})
    with pytest.raises(SchemaValidationError):
        validate_value("bad", {"type": "object"})
    with pytest.raises(SchemaValidationError):
        validate_value({}, {"type": "object", "properties": {}, "required": ["job"]})
    with pytest.raises(SchemaValidationError):
        validate_value(
            {"x": 1}, {"type": "object", "properties": {}, "additionalProperties": False}
        )
    with pytest.raises(SchemaValidationError):
        validate_value(
            {"x": "bad"},
            {
                "type": "object",
                "properties": {},
                "additionalProperties": {"type": "integer"},
            },
        )
    with pytest.raises(SchemaValidationError):
        validate_value("bad", {"type": "mystery"})

    assert coerce_value("3", int | str) == 3
    assert coerce_value("mesh", int | str) == "mesh"
    assert coerce_value([1, 2], tuple[int, ...]) == (1, 2)
    assert coerce_value({"a": 1}, dict[str, int]) == {"a": 1}
    assert to_json_compatible(Path("mesh.txt")) == "mesh.txt"
    assert to_json_compatible((1, 2)) == [1, 2]

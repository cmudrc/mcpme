"""Deterministic parsing for Google-style wrapper docstrings."""

from __future__ import annotations

from dataclasses import dataclass, field
from inspect import cleandoc

_SECTION_HEADERS = {"Args", "Arguments", "Returns", "MCP"}
_SUPPORTED_MCP_KEYS = {
    "name",
    "title",
    "read_only",
    "destructive",
    "idempotent",
    "open_world",
    "hidden",
}


@dataclass(frozen=True, slots=True)
class ParsedDocstring:
    """Represent the parsed structured pieces of a Google-style docstring.

    Args:
        summary: One-line summary text.
        param_descriptions: Parameter descriptions keyed by parameter name.
        returns_description: Optional return value description.
        mcp_metadata: Optional MCP metadata parsed from the ``MCP:`` section.
    """

    summary: str = ""
    param_descriptions: dict[str, str] = field(default_factory=dict)
    returns_description: str | None = None
    mcp_metadata: dict[str, object] = field(default_factory=dict)


def parse_google_docstring(docstring: str | None) -> ParsedDocstring:
    """Parse a deterministic subset of Google-style docstrings.

    Args:
        docstring: Raw docstring text.

    Returns:
        The parsed docstring representation.

    Raises:
        ValueError: Raised when the ``MCP:`` section contains an unknown key.
    """
    if not docstring:
        return ParsedDocstring()
    lines = cleandoc(docstring).splitlines()
    sections = _split_sections(lines)
    summary_lines = [line.strip() for line in sections["Summary"] if line.strip()]
    return ParsedDocstring(
        summary=" ".join(summary_lines),
        param_descriptions=_parse_args_section(sections.get("Args", sections.get("Arguments", ()))),
        returns_description=_parse_returns_section(sections.get("Returns", ())),
        mcp_metadata=_parse_mcp_section(sections.get("MCP", ())),
    )


def _split_sections(lines: list[str]) -> dict[str, list[str]]:
    """Split cleaned docstring lines into high-level sections."""
    sections: dict[str, list[str]] = {"Summary": []}
    current_section = "Summary"
    for line in lines:
        stripped = line.strip()
        if stripped.endswith(":") and stripped[:-1] in _SECTION_HEADERS:
            current_section = stripped[:-1]
            sections.setdefault(current_section, [])
            continue
        sections.setdefault(current_section, []).append(line)
    return sections


def _parse_args_section(lines: list[str] | tuple[str, ...] | None) -> dict[str, str]:
    """Parse the ``Args:`` section into parameter descriptions."""
    if not lines:
        return {}
    descriptions: dict[str, str] = {}
    current_name: str | None = None
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        if ":" in line and not raw_line.startswith(" " * 8):
            name_part, description = line.split(":", 1)
            current_name = name_part.split("(", 1)[0].strip()
            descriptions[current_name] = description.strip()
            continue
        if current_name is not None:
            descriptions[current_name] = f"{descriptions[current_name]} {line}".strip()
    return descriptions


def _parse_returns_section(lines: list[str] | tuple[str, ...] | None) -> str | None:
    """Parse the ``Returns:`` section into one compact description."""
    if not lines:
        return None
    normalized = [line.strip() for line in lines if line.strip()]
    if not normalized:
        return None
    return " ".join(normalized)


def _parse_mcp_section(lines: list[str] | tuple[str, ...] | None) -> dict[str, object]:
    """Parse the optional ``MCP:`` section into deterministic metadata."""
    if not lines:
        return {}
    metadata: dict[str, object] = {}
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        if ":" not in line:
            continue
        key, raw_value = line.split(":", 1)
        normalized_key = key.strip()
        if normalized_key not in _SUPPORTED_MCP_KEYS:
            raise ValueError(f"Unsupported MCP metadata key: {normalized_key}")
        metadata[normalized_key] = _coerce_metadata_value(raw_value.strip())
    return metadata


def _coerce_metadata_value(value: str) -> object:
    """Convert a docstring metadata literal into a Python value."""
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    return value

"""Deterministic parsing for wrapper docstrings.

The maintained repository standard is Sphinx field-list docstrings. The parser
focuses on harvesting that structured metadata deterministically so wrapper
discovery, schema generation, and generated documentation stay aligned.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from inspect import cleandoc

_MCP_SECTION_HEADER = "MCP:"
_SUPPORTED_MCP_KEYS = {
    "name",
    "title",
    "read_only",
    "destructive",
    "idempotent",
    "open_world",
    "hidden",
}
_PARAM_FIELD_PATTERN = re.compile(
    r"^:(?:param|parameter|arg|argument)\s+([A-Za-z_][A-Za-z0-9_\.]*)\s*:\s*(.*)$"
)
_RETURNS_FIELD_PATTERN = re.compile(r"^:(?:returns?|return)\s*:\s*(.*)$")
_TYPE_FIELD_PATTERN = re.compile(r"^:(?:type|vartype)\s+([A-Za-z_][A-Za-z0-9_\.]*)\s*:\s*(.*)$")
_RTYPE_FIELD_PATTERN = re.compile(r"^:rtype\s*:\s*(.*)$")


@dataclass(frozen=True, slots=True)
class ParsedDocstring:
    """Represent the parsed structured pieces of a supported docstring.

    :param summary: One-line summary text.
    :param param_descriptions: Parameter descriptions keyed by parameter name.
    :param returns_description: Optional return value description.
    :param mcp_metadata: Optional MCP metadata parsed from the ``MCP:`` section.
    """

    summary: str = ""
    param_descriptions: dict[str, str] = field(default_factory=dict)
    returns_description: str | None = None
    mcp_metadata: dict[str, object] = field(default_factory=dict)


def parse_docstring(docstring: str | None) -> ParsedDocstring:
    """Parse the maintained deterministic docstring subset.

    The parser prefers deterministic description harvesting over trying to
    understand every docstring convention in the wild.

    :param docstring: Raw docstring text.
    :returns: The parsed docstring representation.
    :raises ValueError: Raised when the ``MCP:`` section contains an unknown key.
    """
    if not docstring:
        return ParsedDocstring()
    lines = cleandoc(docstring).splitlines()
    summary_lines, param_descriptions, returns_description, mcp_lines = _split_sections(lines)
    return ParsedDocstring(
        summary=" ".join(line.strip() for line in summary_lines if line.strip()),
        param_descriptions=param_descriptions,
        returns_description=returns_description,
        mcp_metadata=_parse_mcp_section(mcp_lines),
    )


def _split_sections(
    lines: list[str],
) -> tuple[list[str], dict[str, str], str | None, list[str]]:
    """Split a cleaned docstring into summary, field lists, and MCP metadata.

    :param lines: Cleaned docstring lines.
    :returns: Summary lines, parsed parameter descriptions, parsed return text,
        and raw ``MCP:`` section lines.
    """
    summary_lines: list[str] = []
    current_param_name: str | None = None
    current_target: str | None = None
    field_param_descriptions: dict[str, str] = {}
    field_returns_description: str | None = None
    mcp_lines: list[str] = []
    in_mcp_section = False

    for line in lines:
        stripped = line.strip()
        if in_mcp_section:
            if stripped.startswith(":"):
                in_mcp_section = False
            else:
                mcp_lines.append(line)
                continue
        param_match = _PARAM_FIELD_PATTERN.match(stripped)
        if param_match is not None:
            current_param_name = param_match.group(1)
            current_target = "param"
            field_param_descriptions[current_param_name] = param_match.group(2).strip()
            continue
        returns_match = _RETURNS_FIELD_PATTERN.match(stripped)
        if returns_match is not None:
            current_param_name = None
            current_target = "returns"
            field_returns_description = returns_match.group(1).strip() or None
            continue
        if _TYPE_FIELD_PATTERN.match(stripped) or _RTYPE_FIELD_PATTERN.match(stripped):
            current_param_name = None
            current_target = None
            continue
        if stripped == _MCP_SECTION_HEADER:
            current_param_name = None
            current_target = None
            in_mcp_section = True
            mcp_lines.append(line)
            continue
        if stripped.startswith(":"):
            current_param_name = None
            current_target = None
            continue
        if current_target == "param" and current_param_name is not None:
            if stripped:
                existing = field_param_descriptions.get(current_param_name, "").strip()
                field_param_descriptions[current_param_name] = f"{existing} {stripped}".strip()
            continue
        if current_target == "returns":
            if stripped:
                if field_returns_description is not None:
                    field_returns_description = f"{field_returns_description} {stripped}".strip()
                else:
                    field_returns_description = stripped
            continue
        summary_lines.append(line)
    return summary_lines, field_param_descriptions, field_returns_description, mcp_lines


def _parse_mcp_section(lines: list[str] | tuple[str, ...] | None) -> dict[str, object]:
    """Parse the optional ``MCP:`` section into deterministic metadata."""
    if not lines:
        return {}
    metadata: dict[str, object] = {}
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line == _MCP_SECTION_HEADER:
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

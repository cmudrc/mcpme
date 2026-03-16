"""Configuration models and loaders for deterministic wrappers."""

from __future__ import annotations

import argparse
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .manifest import (
    ArtifactPolicy,
    FileTemplate,
    RetainedPathSpec,
    SubprocessResultSpec,
    ToolAnnotations,
)

_PYTHON_DISCOVERY_MODES = frozenset({"source", "import"})


@dataclass(frozen=True, slots=True)
class ToolOverride:
    """Represent user-supplied metadata overrides for one tool.

    :param name: Optional override for the canonical tool name.
    :param title: Optional override for the MCP title.
    :param description: Optional override for the tool description.
    :param hidden: Whether to suppress the tool from the manifest.
    :param annotations: Optional behavior annotations.
    """

    name: str | None = None
    title: str | None = None
    description: str | None = None
    hidden: bool = False
    annotations: ToolAnnotations = field(default_factory=ToolAnnotations)


@dataclass(frozen=True, slots=True)
class SubprocessToolConfig:
    """Describe a manifest-driven subprocess tool.

    :param name: Canonical tool name.
    :param description: Human-readable tool description.
    :param argv: Deterministic argv template.
    :param input_schema: JSON Schema for input validation.
    :param title: Optional MCP title.
    :param output_schema: Optional JSON Schema for structured output.
    :param annotations: Optional behavior annotations.
    :param cwd: Optional working directory override.
    :param env: Deterministic environment variable templates.
    :param stdin_template: Optional standard input template.
    :param files: Rendered input file templates.
    :param retained_paths: Explicit output paths copied into retained artifacts.
    :param result: Result extraction rule.
    :param timeout_seconds: Optional subprocess timeout in seconds.
    """

    name: str
    description: str
    argv: tuple[str, ...]
    input_schema: dict[str, Any]
    title: str | None = None
    output_schema: dict[str, Any] | None = None
    annotations: ToolAnnotations = field(default_factory=ToolAnnotations)
    cwd: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    stdin_template: str | None = None
    files: tuple[FileTemplate, ...] = ()
    retained_paths: tuple[RetainedPathSpec, ...] = ()
    result: SubprocessResultSpec = field(default_factory=SubprocessResultSpec)
    timeout_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class ArgparseCommand:
    """Represent an explicitly registered ``argparse`` command target.

    :param name: Canonical tool name.
    :param parser: Parser object used for deterministic schema extraction.
    :param command: Subprocess command prefix used to execute the CLI.
    :param description: Optional override for the tool description.
    :param title: Optional override for the MCP title.
    :param annotations: Optional behavior annotations.
    """

    name: str
    parser: argparse.ArgumentParser
    command: tuple[str, ...]
    description: str | None = None
    title: str | None = None
    annotations: ToolAnnotations = field(default_factory=ToolAnnotations)


@dataclass(frozen=True, slots=True)
class ManifestConfig:
    """Represent the loaded project configuration.

    :param targets: Discovery targets loaded from config.
    :param overrides: Per-tool metadata overrides.
    :param subprocess_tools: Explicit subprocess tools.
    :param artifact_policy: Artifact retention policy.
    :param python_discovery_mode: Discovery mode used for Python files/modules.
    """

    targets: tuple[str, ...] = ()
    overrides: dict[str, ToolOverride] = field(default_factory=dict)
    subprocess_tools: tuple[SubprocessToolConfig, ...] = ()
    artifact_policy: ArtifactPolicy = field(default_factory=ArtifactPolicy)
    python_discovery_mode: str = "source"


def _resolve_config_table(data: dict[str, Any]) -> dict[str, Any]:
    """Return the ``tool.mcpme`` table from parsed TOML data."""
    if "tool" in data and isinstance(data["tool"], dict) and "mcpme" in data["tool"]:
        table = data["tool"]["mcpme"]
        if isinstance(table, dict):
            return table
    if "mcpme" in data and isinstance(data["mcpme"], dict):
        return data["mcpme"]
    return {}


def _parse_annotations(data: dict[str, Any]) -> ToolAnnotations:
    """Build annotations from a TOML mapping."""
    return ToolAnnotations(
        read_only=_optional_bool(data.get("read_only")),
        destructive=_optional_bool(data.get("destructive")),
        idempotent=_optional_bool(data.get("idempotent")),
        open_world=_optional_bool(data.get("open_world")),
    )


def _optional_bool(value: Any) -> bool | None:
    """Return a boolean or ``None`` from TOML data."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    raise ValueError(f"Expected a boolean value, received {value!r}.")


def _load_toml_path(config_path: Path | None) -> tuple[Path | None, dict[str, Any]]:
    """Load TOML data from an explicit or discovered configuration path."""
    candidate_paths = (
        (config_path,) if config_path is not None else (Path("pyproject.toml"), Path("mcpme.toml"))
    )
    for path in candidate_paths:
        if path is not None and path.exists():
            return path, tomllib.loads(path.read_text(encoding="utf-8"))
    return config_path, {}


def load_config(config_path: str | Path | None = None) -> ManifestConfig:
    """Load deterministic wrapper configuration.

    :param config_path: Optional explicit path to a TOML file.
    :returns: The parsed manifest configuration.
    """
    resolved_path, data = _load_toml_path(Path(config_path) if config_path is not None else None)
    table = _resolve_config_table(data)
    root_dir = Path(table.get("artifact_root", ".mcpme-artifacts"))
    if resolved_path is not None and not root_dir.is_absolute():
        root_dir = resolved_path.resolve().parent / root_dir
    python_discovery_mode = str(table.get("python_discovery_mode", "source"))
    if python_discovery_mode not in _PYTHON_DISCOVERY_MODES:
        raise ValueError(
            f"Unsupported python discovery mode {python_discovery_mode!r}. "
            f"Expected one of {sorted(_PYTHON_DISCOVERY_MODES)!r}."
        )
    overrides = {
        name: ToolOverride(
            name=entry.get("name"),
            title=entry.get("title"),
            description=entry.get("description"),
            hidden=bool(entry.get("hidden", False)),
            annotations=_parse_annotations(entry),
        )
        for name, entry in table.get("tool", {}).items()
        if isinstance(entry, dict)
    }
    subprocess_tools = tuple(_parse_subprocess_tool(entry) for entry in table.get("subprocess", []))
    return ManifestConfig(
        targets=tuple(str(item) for item in table.get("targets", ())),
        overrides=overrides,
        subprocess_tools=subprocess_tools,
        artifact_policy=ArtifactPolicy(
            mode=str(table.get("artifact_mode", "full")),
            root_dir=root_dir,
        ),
        python_discovery_mode=python_discovery_mode,
    )


def _parse_subprocess_tool(data: dict[str, Any]) -> SubprocessToolConfig:
    """Parse one subprocess tool configuration entry."""
    files = tuple(
        FileTemplate(path=str(file_data["path"]), template=str(file_data["template"]))
        for file_data in data.get("files", [])
    )
    retained_paths = tuple(
        RetainedPathSpec(
            path=str(path_data["path"]),
            kind=str(path_data.get("kind", "auto")),
            optional=bool(path_data.get("optional", False)),
            when=str(path_data.get("when", "success")),
        )
        for path_data in data.get("outputs", [])
    )
    result = SubprocessResultSpec(
        kind=str(data.get("result_kind", "stdout_text")),
        path=str(data["result_path"]) if "result_path" in data else None,
    )
    return SubprocessToolConfig(
        name=str(data["name"]),
        description=str(data["description"]),
        argv=tuple(str(item) for item in data.get("argv", ())),
        input_schema=dict(data.get("input_schema", {})),
        title=str(data["title"]) if "title" in data else None,
        output_schema=dict(data["output_schema"]) if "output_schema" in data else None,
        annotations=_parse_annotations(data),
        cwd=str(data["cwd"]) if "cwd" in data else None,
        env={str(key): str(value) for key, value in data.get("env", {}).items()},
        stdin_template=str(data["stdin_template"]) if "stdin_template" in data else None,
        files=files,
        retained_paths=retained_paths,
        result=result,
        timeout_seconds=float(data["timeout_seconds"]) if "timeout_seconds" in data else None,
    )

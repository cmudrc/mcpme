"""Serializable manifest models for deterministic MCP wrappers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

_ARTIFACT_MODES = frozenset({"none", "summary", "full"})
_RETAINED_PATH_KINDS = frozenset({"auto", "file", "directory"})
_RETAINED_PATH_WHEN = frozenset({"always", "success", "error"})


@dataclass(frozen=True, slots=True)
class ArtifactPolicy:
    """Control how execution artifacts are retained.

    :param mode: Retention mode. Supported values are ``"none"``,
        ``"summary"``, and ``"full"``.
    :param root_dir: Directory where retained artifacts are written.
    """

    mode: str = "full"
    root_dir: Path = Path(".mcpme-artifacts")

    def __post_init__(self) -> None:
        """Validate artifact policy values early."""
        if self.mode not in _ARTIFACT_MODES:
            raise ValueError(
                f"Unsupported artifact mode {self.mode!r}. "
                f"Expected one of {sorted(_ARTIFACT_MODES)!r}."
            )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation."""
        return {"mode": self.mode, "root_dir": str(self.root_dir)}


@dataclass(frozen=True, slots=True)
class ToolAnnotations:
    """Represent MCP tool annotations.

    :param read_only: Whether the tool is read-only.
    :param destructive: Whether the tool may mutate or delete state.
    :param idempotent: Whether repeated calls with the same input are stable.
    :param open_world: Whether the tool may interact with external state.
    """

    read_only: bool | None = None
    destructive: bool | None = None
    idempotent: bool | None = None
    open_world: bool | None = None

    def to_mcp(self) -> dict[str, bool]:
        """Return the annotation mapping expected by the MCP tools surface."""
        mapping = {
            "readOnlyHint": self.read_only,
            "destructiveHint": self.destructive,
            "idempotentHint": self.idempotent,
            "openWorldHint": self.open_world,
        }
        return {key: value for key, value in mapping.items() if value is not None}


@dataclass(frozen=True, slots=True)
class SourceReference:
    """Describe where a manifest entry came from.

    :param kind: Source type, such as ``"module"``, ``"file"``, or
        ``"subprocess"``.
    :param target: The original target identifier.
    :param location: Optional more specific source location.
    """

    kind: str
    target: str
    location: str | None = None

    def to_dict(self) -> dict[str, str]:
        """Return a JSON-compatible representation."""
        data = {"kind": self.kind, "target": self.target}
        if self.location is not None:
            data["location"] = self.location
        return data


@dataclass(frozen=True, slots=True)
class ToolManifest:
    """Describe one deterministic MCP tool.

    :param name: Canonical MCP tool name.
    :param description: Human-readable tool description.
    :param input_schema: JSON Schema for tool inputs.
    :param source: Source reference for the tool.
    :param binding_kind: Runtime binding type used by the executor.
    :param title: Optional MCP title.
    :param output_schema: Optional JSON Schema for structured output.
    :param annotations: Optional behavioral annotations.
    :param aliases: Optional deterministic alternate names accepted by the
        runtime.
    """

    name: str
    description: str
    input_schema: dict[str, Any]
    source: SourceReference
    binding_kind: str
    title: str | None = None
    output_schema: dict[str, Any] | None = None
    annotations: ToolAnnotations = field(default_factory=ToolAnnotations)
    aliases: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation."""
        data = {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
            "source": self.source.to_dict(),
            "bindingKind": self.binding_kind,
        }
        if self.title is not None:
            data["title"] = self.title
        if self.output_schema is not None:
            data["outputSchema"] = self.output_schema
        annotations = self.annotations.to_mcp()
        if annotations:
            data["annotations"] = annotations
        if self.aliases:
            data["aliases"] = list(self.aliases)
        return data

    def to_mcp_tool(self) -> dict[str, Any]:
        """Return the MCP ``tools/list`` representation."""
        data = {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }
        if self.title is not None:
            data["title"] = self.title
        if self.output_schema is not None:
            data["outputSchema"] = self.output_schema
        annotations = self.annotations.to_mcp()
        if annotations:
            data["annotations"] = annotations
        return data


@dataclass(frozen=True, slots=True)
class RetainedPathSpec:
    """Describe a subprocess output path retained as a first-class artifact.

    :param path: Relative path rooted at the executed working directory.
    :param kind: Expected output kind. ``"auto"`` accepts either file or
        directory.
    :param optional: Whether missing outputs should be tolerated.
    :param when: When the path should be copied into retained artifacts.
    """

    path: str
    kind: str = "auto"
    optional: bool = False
    when: str = "success"

    def __post_init__(self) -> None:
        """Validate retained-path configuration values early."""
        if self.kind not in _RETAINED_PATH_KINDS:
            raise ValueError(
                f"Unsupported retained path kind {self.kind!r}. "
                f"Expected one of {sorted(_RETAINED_PATH_KINDS)!r}."
            )
        if self.when not in _RETAINED_PATH_WHEN:
            raise ValueError(
                f"Unsupported retained path timing {self.when!r}. "
                f"Expected one of {sorted(_RETAINED_PATH_WHEN)!r}."
            )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation."""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class FileTemplate:
    """Describe a rendered file used by a subprocess tool.

    :param path: Relative output path in the working directory.
    :param template: Deterministic text template rendered with tool arguments.
    """

    path: str
    template: str

    def to_dict(self) -> dict[str, str]:
        """Return a JSON-compatible representation."""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SubprocessResultSpec:
    """Describe how to extract a subprocess result.

    :param kind: Extraction mode, such as ``"stdout_text"``, ``"file_json"``,
        ``"file_bytes"``, or ``"directory_manifest"``.
    :param path: Optional relative path for file-based extraction modes.
    """

    kind: str = "stdout_text"
    path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation."""
        data = {"kind": self.kind}
        if self.path is not None:
            data["path"] = self.path
        return data


@dataclass(frozen=True, slots=True)
class ArgparseOptionSpec:
    """Describe one argparse action in a serializable form.

    :param dest: Destination name.
    :param option_strings: Flag spellings for optional arguments.
    :param positional: Whether the argument is positional.
    :param required: Whether the argument is required.
    :param nargs: ``argparse`` cardinality metadata.
    :param action: Normalized action type.
    """

    dest: str
    option_strings: tuple[str, ...]
    positional: bool
    required: bool
    nargs: str | int | None
    action: str


@dataclass(frozen=True, slots=True)
class Manifest:
    """Bundle the generated tool manifests and runtime bindings.

    :param tools: Ordered collection of generated tool manifests.
    :param artifact_policy: Artifact retention policy for execution.
    :param runtime_bindings: Runtime-only binding objects keyed by tool name.
    """

    tools: tuple[ToolManifest, ...]
    artifact_policy: ArtifactPolicy = field(default_factory=ArtifactPolicy)
    runtime_bindings: dict[str, object] = field(
        default_factory=dict,
        repr=False,
        compare=False,
    )

    @property
    def tool_names(self) -> tuple[str, ...]:
        """Return the manifest tool names in order."""
        return tuple(tool.name for tool in self.tools)

    def get_tool(self, name: str) -> ToolManifest:
        """Return one tool manifest by name.

        :param name: Tool name to look up.
        :returns: The matching tool manifest.
        :raises KeyError: Raised when the tool does not exist.
        """
        for tool in self.tools:
            if tool.name == name or name in tool.aliases:
                return tool
        raise KeyError(name)

    def get_binding(self, name: str) -> object:
        """Return the runtime binding for one tool.

        :param name: Tool name to look up.
        :returns: The matching runtime binding object.
        :raises KeyError: Raised when the binding does not exist.
        """
        return self.runtime_bindings[self.get_tool(name).name]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible manifest representation."""
        return {
            "artifactPolicy": self.artifact_policy.to_dict(),
            "tools": [tool.to_dict() for tool in self.tools],
        }

"""Deterministic target discovery and manifest generation."""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib
import inspect
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any, get_type_hints

from ._python_tools import (
    DiscoveredPythonTool,
    StaticPythonResolver,
    _public_names_from_ast,
    load_module_from_path,
)
from .config import (
    ArgparseCommand,
    ManifestConfig,
    SubprocessToolConfig,
    ToolOverride,
    load_config,
)
from .docstrings import parse_google_docstring
from .execution import (
    ArgparseCommandBinding,
    PythonCallableBinding,
    PythonFileBinding,
    PythonModuleBinding,
    SubprocessBinding,
)
from .manifest import (
    ArgparseOptionSpec,
    ArtifactPolicy,
    Manifest,
    SourceReference,
    ToolAnnotations,
    ToolManifest,
)
from .schema import SchemaGenerationError, schema_from_annotation, to_json_compatible

Target = str | Path | Callable[..., Any] | ArgparseCommand


def build_manifest(
    *,
    targets: Sequence[Target] | None = None,
    config_path: str | Path | None = None,
    artifact_root: str | Path | None = None,
) -> Manifest:
    """Build a deterministic manifest from configured and explicit targets.

    Args:
        targets: Optional explicit discovery targets.
        config_path: Optional TOML configuration path.
        artifact_root: Optional artifact root override.

    Returns:
        The generated manifest.
    """
    config = load_config(config_path)
    policy = _resolve_artifact_policy(config, artifact_root)
    resolver = StaticPythonResolver()
    discovered_entries: list[tuple[ToolManifest, object]] = []
    for subprocess_tool in config.subprocess_tools:
        override = config.overrides.get(subprocess_tool.name)
        discovered_entries.append(_build_subprocess_manifest(subprocess_tool, override))
    for target in (*config.targets, *(targets or ())):
        discovered_entries.extend(_discover_target(target, config, resolver))
    normalized_entries = _normalize_discovered_tools(discovered_entries)
    return Manifest(
        tools=tuple(tool for tool, _ in normalized_entries),
        artifact_policy=policy,
        runtime_bindings={tool.name: binding for tool, binding in normalized_entries},
    )


def _resolve_artifact_policy(
    config: ManifestConfig,
    artifact_root: str | Path | None,
) -> ArtifactPolicy:
    """Resolve the effective artifact policy."""
    if artifact_root is None:
        return config.artifact_policy
    return ArtifactPolicy(mode=config.artifact_policy.mode, root_dir=Path(artifact_root))


def _discover_target(
    target: Target | str,
    config: ManifestConfig,
    resolver: StaticPythonResolver,
) -> list[tuple[ToolManifest, object]]:
    """Discover manifest entries for one explicit target."""
    if isinstance(target, ArgparseCommand):
        discovered = _build_argparse_manifest(target)
        override = config.overrides.get(discovered[0].name)
        return [_apply_override(discovered, override)]
    if callable(target):
        discovered = _build_callable_manifest(target)
        override = config.overrides.get(discovered[0].name)
        return [_apply_override(discovered, override)]
    path = Path(target)
    if path.exists():
        if path.is_dir():
            return _discover_directory(path, config, resolver)
        return _discover_python_file(path, config, resolver)
    return _discover_module(str(target), config, resolver)


def _discover_directory(
    path: Path,
    config: ManifestConfig,
    resolver: StaticPythonResolver,
) -> list[tuple[ToolManifest, object]]:
    """Discover tools from a directory of Python files."""
    discovered: list[tuple[ToolManifest, object]] = []
    for child in sorted(path.glob("*.py")):
        if child.name == "__init__.py":
            continue
        discovered.extend(_discover_python_file(child, config, resolver))
    return discovered


def _discover_python_file(
    path: Path,
    config: ManifestConfig,
    resolver: StaticPythonResolver,
) -> list[tuple[ToolManifest, object]]:
    """Discover tools from a Python file target."""
    if config.python_discovery_mode == "import":
        return _discover_python_file_via_import(path, config)
    discovered = resolver.discover_file(path)
    return [
        _apply_override(
            _materialize_source_tool(entry),
            config.overrides.get(entry.tool.name),
        )
        for entry in discovered
    ]


def _discover_module(
    module_name: str,
    config: ManifestConfig,
    resolver: StaticPythonResolver,
) -> list[tuple[ToolManifest, object]]:
    """Discover tools from an importable module or package."""
    if config.python_discovery_mode == "import":
        return _discover_module_via_import(module_name, config)
    discovered = resolver.discover_module(module_name)
    return [
        _apply_override(
            _materialize_source_tool(entry),
            config.overrides.get(entry.tool.name),
        )
        for entry in discovered
    ]


def _discover_python_file_via_import(
    path: Path,
    config: ManifestConfig,
) -> list[tuple[ToolManifest, object]]:
    """Discover tools from a Python file by importing it."""
    public_names = _public_names_from_python_file(path)
    module = load_module_from_path(path)
    discovered: list[tuple[ToolManifest, object]] = []
    for name in public_names:
        attribute = getattr(module, name)
        if not callable(attribute):
            continue
        tool, binding = _build_python_tool_manifest(
            attribute,
            SourceReference(kind="file", target=str(path), location=f"{path}:{name}"),
        )
        discovered.append(_apply_override((tool, binding), config.overrides.get(tool.name)))
    return discovered


def _discover_module_via_import(
    module_name: str,
    config: ManifestConfig,
) -> list[tuple[ToolManifest, object]]:
    """Discover tools from an importable module by reflecting on it."""
    module = importlib.import_module(module_name)
    public_names = _public_names_from_module(module)
    discovered: list[tuple[ToolManifest, object]] = []
    for name in public_names:
        attribute = getattr(module, name)
        if not callable(attribute):
            continue
        tool, binding = _build_python_tool_manifest(
            attribute,
            SourceReference(
                kind="module",
                target=module_name,
                location=f"{module_name}.{attribute.__qualname__}",
            ),
        )
        discovered.append(_apply_override((tool, binding), config.overrides.get(tool.name)))
    return discovered


def _materialize_source_tool(discovered: DiscoveredPythonTool) -> tuple[ToolManifest, object]:
    """Convert a statically discovered Python tool into a runtime binding pair."""
    if discovered.binding_module_name is not None:
        binding: object = PythonModuleBinding(
            module_name=discovered.binding_module_name,
            qualname=discovered.binding_qualname,
        )
    else:
        if discovered.binding_file_path is None:
            raise ValueError("Source-discovered tools require a module name or file path.")
        binding = PythonFileBinding(
            file_path=discovered.binding_file_path,
            qualname=discovered.binding_qualname,
        )
    return discovered.tool, binding


def _public_names_from_module(module: Any) -> tuple[str, ...]:
    """Return the public callable names for an imported module."""
    if hasattr(module, "__all__"):
        return tuple(name for name in module.__all__ if callable(getattr(module, name, None)))
    return tuple(
        sorted(
            name
            for name, value in vars(module).items()
            if not name.startswith("_") and callable(value) and not inspect.isclass(value)
        )
    )


def _public_names_from_python_file(path: Path) -> tuple[str, ...]:
    """Return the public top-level callable names for a Python file."""
    module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return _public_names_from_ast(module)


def _load_module_from_path(path: Path) -> Any:
    """Load a Python file under a stable synthetic module name."""
    return load_module_from_path(path)


def _build_callable_manifest(target: Callable[..., Any]) -> tuple[ToolManifest, object]:
    """Build a manifest entry for one directly registered callable."""
    import_path = f"{target.__module__}.{target.__qualname__}"
    return _build_python_tool_manifest(
        target,
        SourceReference(kind="callable", target=import_path, location=import_path),
    )


def _build_python_tool_manifest(
    target: Callable[..., Any],
    source: SourceReference,
) -> tuple[ToolManifest, object]:
    """Build a manifest entry for one Python callable."""
    signature = inspect.signature(target)
    hints = get_type_hints(target, include_extras=True)
    docstring = parse_google_docstring(inspect.getdoc(target))
    properties: dict[str, Any] = {}
    required: list[str] = []
    for parameter in signature.parameters.values():
        if parameter.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.VAR_POSITIONAL):
            raise SchemaGenerationError("Positional-only and *args parameters are not supported.")
        if parameter.kind is inspect.Parameter.VAR_KEYWORD:
            raise SchemaGenerationError("**kwargs parameters are not supported.")
        schema = schema_from_annotation(hints.get(parameter.name, parameter.annotation))
        if parameter.name in docstring.param_descriptions:
            schema["description"] = docstring.param_descriptions[parameter.name]
        if parameter.default is inspect.Signature.empty:
            required.append(parameter.name)
        else:
            schema["default"] = to_json_compatible(parameter.default)
        properties[parameter.name] = schema
    input_schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        input_schema["required"] = required
    output_schema: dict[str, Any] | None = None
    return_annotation = hints.get("return", signature.return_annotation)
    if return_annotation is not inspect.Signature.empty:
        output_schema = schema_from_annotation(return_annotation)
    annotations = ToolAnnotations(
        read_only=_optional_bool(docstring.mcp_metadata.get("read_only")),
        destructive=_optional_bool(docstring.mcp_metadata.get("destructive")),
        idempotent=_optional_bool(docstring.mcp_metadata.get("idempotent")),
        open_world=_optional_bool(docstring.mcp_metadata.get("open_world")),
    )
    tool_name = _optional_str(docstring.mcp_metadata.get("name")) or target.__name__
    tool = ToolManifest(
        name=tool_name,
        title=_optional_str(docstring.mcp_metadata.get("title")),
        description=docstring.summary or f"Execute {target.__name__.replace('_', ' ')}.",
        input_schema=input_schema,
        output_schema=output_schema,
        annotations=annotations,
        source=source,
        binding_kind="python",
    )
    if bool(docstring.mcp_metadata.get("hidden", False)):
        raise ValueError(f"Tool {tool.name!r} is hidden by docstring metadata.")
    return tool, PythonCallableBinding(target)


def _build_subprocess_manifest(
    config: SubprocessToolConfig,
    override: ToolOverride | None,
) -> tuple[ToolManifest, object]:
    """Build a manifest entry for one configured subprocess tool."""
    tool = ToolManifest(
        name=config.name,
        title=config.title,
        description=config.description,
        input_schema=config.input_schema,
        output_schema=config.output_schema,
        annotations=config.annotations,
        source=SourceReference(kind="subprocess", target=config.name, location=config.cwd),
        binding_kind="subprocess",
    )
    binding = SubprocessBinding(
        argv=config.argv,
        cwd=config.cwd,
        env=config.env,
        stdin_template=config.stdin_template,
        files=config.files,
        retained_paths=config.retained_paths,
        result=config.result,
        timeout_seconds=config.timeout_seconds,
    )
    return _apply_override((tool, binding), override)


def _build_argparse_manifest(target: ArgparseCommand) -> tuple[ToolManifest, object]:
    """Build a manifest entry for one registered ``argparse`` command."""
    properties: dict[str, Any] = {}
    required: list[str] = []
    action_specs: list[ArgparseOptionSpec] = []
    for action in target.parser._actions:
        if action.dest == "help":
            continue
        action_schema = _schema_from_argparse_action(action)
        if action.help:
            action_schema["description"] = action.help
        properties[action.dest] = action_schema
        positional = len(action.option_strings) == 0
        if action.required or (positional and action.nargs not in ("*", "?")):
            required.append(action.dest)
        action_specs.append(
            ArgparseOptionSpec(
                dest=action.dest,
                option_strings=tuple(action.option_strings),
                positional=positional,
                required=action.required or (positional and action.nargs not in ("*", "?")),
                nargs=action.nargs,
                action=_normalize_argparse_action(action),
            )
        )
    input_schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        input_schema["required"] = required
    tool = ToolManifest(
        name=target.name,
        title=target.title,
        description=target.description
        or target.parser.description
        or f"Execute {target.name.replace('_', ' ')}.",
        input_schema=input_schema,
        annotations=target.annotations,
        source=SourceReference(
            kind="argparse",
            target=target.name,
            location=" ".join(target.command),
        ),
        binding_kind="argparse",
    )
    return tool, ArgparseCommandBinding(command=target.command, actions=tuple(action_specs))


def _schema_from_argparse_action(action: argparse.Action) -> dict[str, Any]:
    """Build JSON Schema for one ``argparse`` action."""
    if isinstance(action, argparse._StoreTrueAction):
        return {"type": "boolean", "default": False}
    if isinstance(action, argparse._StoreFalseAction):
        return {"type": "boolean", "default": True}
    if action.choices is not None:
        values = list(action.choices)
        schema = {"enum": values, "type": _infer_choice_type(values)}
    elif action.type is int:
        schema = {"type": "integer"}
    elif action.type is float:
        schema = {"type": "number"}
    else:
        schema = {"type": "string"}
    if action.nargs in ("*", "+") or (isinstance(action.nargs, int) and action.nargs > 1):
        return {"type": "array", "items": schema}
    if action.default not in (None, inspect.Signature.empty):
        schema["default"] = action.default
    return schema


def _infer_choice_type(values: list[Any]) -> str:
    """Infer a JSON Schema type from ``argparse`` choices."""
    if all(isinstance(value, int) and not isinstance(value, bool) for value in values):
        return "integer"
    if all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in values):
        return "number"
    return "string"


def _normalize_argparse_action(action: argparse.Action) -> str:
    """Normalize an ``argparse`` action into a stable action name."""
    if isinstance(action, argparse._StoreTrueAction):
        return "store_true"
    if isinstance(action, argparse._StoreFalseAction):
        return "store_false"
    return "store"


def _apply_override(
    discovered: tuple[ToolManifest, object],
    override: ToolOverride | None,
) -> tuple[ToolManifest, object]:
    """Apply a tool override to a discovered manifest entry."""
    tool, binding = discovered
    if override is None:
        return tool, binding
    if override.hidden:
        raise ValueError(f"Tool {tool.name!r} is hidden by configuration.")
    annotations = ToolAnnotations(
        read_only=override.annotations.read_only
        if override.annotations.read_only is not None
        else tool.annotations.read_only,
        destructive=override.annotations.destructive
        if override.annotations.destructive is not None
        else tool.annotations.destructive,
        idempotent=override.annotations.idempotent
        if override.annotations.idempotent is not None
        else tool.annotations.idempotent,
        open_world=override.annotations.open_world
        if override.annotations.open_world is not None
        else tool.annotations.open_world,
    )
    return (
        ToolManifest(
            name=override.name if override.name is not None else tool.name,
            title=override.title if override.title is not None else tool.title,
            description=(
                override.description if override.description is not None else tool.description
            ),
            input_schema=tool.input_schema,
            output_schema=tool.output_schema,
            annotations=annotations,
            aliases=tool.aliases,
            source=tool.source,
            binding_kind=tool.binding_kind,
        ),
        binding,
    )


def _normalize_discovered_tools(
    discovered: list[tuple[ToolManifest, object]],
) -> list[tuple[ToolManifest, object]]:
    """Assign stable canonical names and aliases after discovery completes."""
    counts = Counter(tool.name for tool, _ in discovered)
    used_names: set[str] = set()
    normalized: list[tuple[ToolManifest, object]] = []
    for tool, binding in discovered:
        qualified_name = _qualified_tool_name(tool)
        aliases = tuple(alias for alias in (qualified_name,) if alias != tool.name)
        if counts[tool.name] == 1 and tool.name not in used_names:
            normalized_tool = replace(tool, aliases=aliases)
            used_names.add(normalized_tool.name)
            normalized.append((normalized_tool, binding))
            continue
        canonical_name = qualified_name
        if canonical_name in used_names:
            canonical_name = _fully_qualified_tool_name(tool)
        if canonical_name in used_names:
            canonical_name = f"{canonical_name}__{_tool_source_hash(tool)}"
        normalized_tool = replace(tool, name=canonical_name)
        used_names.add(normalized_tool.name)
        normalized.append((normalized_tool, binding))
    return normalized


def _qualified_tool_name(tool: ToolManifest) -> str:
    """Build a short deterministic qualified tool name."""
    qualifier = _short_source_qualifier(tool.source)
    return tool.name if not qualifier else f"{qualifier}__{tool.name}"


def _fully_qualified_tool_name(tool: ToolManifest) -> str:
    """Build a longer deterministic qualified tool name."""
    qualifier = _long_source_qualifier(tool.source)
    return tool.name if not qualifier else f"{qualifier}__{tool.name}"


def _short_source_qualifier(source: SourceReference) -> str:
    """Return a concise qualifier derived from the source reference."""
    if source.kind == "module":
        return _sanitize_name(source.target.rsplit(".", 1)[-1])
    if source.kind == "file":
        return _sanitize_name(Path(source.target).stem)
    return _sanitize_name(source.target.rsplit(".", 1)[-1])


def _long_source_qualifier(source: SourceReference) -> str:
    """Return a verbose qualifier derived from the source reference."""
    if source.kind == "module":
        return _sanitize_name(source.target.replace(".", "__"))
    if source.kind == "file":
        file_path = Path(source.target)
        if file_path.suffix == ".py":
            file_path = file_path.with_suffix("")
        parts = [part for part in file_path.parts if part not in {"/", ""}]
        return _sanitize_name("__".join(parts[-4:]))
    return _sanitize_name(source.target.replace(".", "__"))


def _tool_source_hash(tool: ToolManifest) -> str:
    """Return a short hash fragment used only for last-resort disambiguation."""
    digest = hashlib.sha256(
        f"{tool.source.kind}:{tool.source.target}:{tool.source.location}".encode()
    ).hexdigest()
    return digest[:8]


def _sanitize_name(value: str) -> str:
    """Normalize a name fragment into a stable MCP-friendly token."""
    sanitized = "".join(character if character.isalnum() else "_" for character in value)
    while "__" in sanitized:
        sanitized = sanitized.replace("__", "_")
    return sanitized.strip("_")


def _optional_bool(value: object) -> bool | None:
    """Return a boolean value or ``None``."""
    return value if isinstance(value, bool) else None


def _optional_str(value: object) -> str | None:
    """Return a string value or ``None``."""
    return value if isinstance(value, str) else None

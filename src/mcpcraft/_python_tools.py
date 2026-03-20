"""Static Python source discovery and lazy loading helpers.

This module keeps deterministic source parsing separate from runtime execution.
Discovery can inspect Python files and source-backed modules without importing
user code, while execution can still resolve the callable lazily when a tool is
actually invoked.
"""

from __future__ import annotations

import ast
import contextlib
import hashlib
import importlib
import importlib.util
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

from .docstrings import parse_docstring
from .manifest import SourceReference, ToolAnnotations, ToolManifest
from .schema import SchemaGenerationError, to_json_compatible

_PRIMITIVE_SCHEMAS = {
    "str": {"type": "string"},
    "int": {"type": "integer"},
    "float": {"type": "number"},
    "bool": {"type": "boolean"},
    "None": {"type": "null"},
}
_ANY_NAMES = {"Any", "typing.Any", "object", "builtins.object"}
_PATH_NAMES = {"Path", "pathlib.Path"}
_PATHLIKE_NAMES = {"PathLike", "os.PathLike"}
_BYTES_NAMES = {"bytes"}
_LIST_NAMES = {"list", "typing.List"}
_TUPLE_NAMES = {"tuple", "typing.Tuple"}
_SET_NAMES = {"set", "typing.Set", "frozenset", "typing.FrozenSet"}
_SEQUENCE_NAMES = {
    "Sequence",
    "typing.Sequence",
    "collections.abc.Sequence",
    "MutableSequence",
    "collections.abc.MutableSequence",
}
_DICT_NAMES = {"dict", "typing.Dict"}
_MAPPING_NAMES = {
    "Mapping",
    "typing.Mapping",
    "collections.abc.Mapping",
    "MutableMapping",
    "collections.abc.MutableMapping",
}
_UNION_NAMES = {"typing.Union", "Union"}
_OPTIONAL_NAMES = {"typing.Optional", "Optional"}
_LITERAL_NAMES = {"typing.Literal", "Literal"}
_ANNOTATED_NAMES = {"typing.Annotated", "Annotated"}
_NDARRAY_NAMES = {"ndarray", "numpy.ndarray", "NDArray", "numpy.typing.NDArray"}
_ENUM_NAMES = {"Enum", "enum.Enum"}
_TYPED_DICT_NAMES = {"TypedDict", "typing.TypedDict"}
_DATACLASS_DECORATORS = {"dataclass", "dataclasses.dataclass"}


@dataclass(frozen=True, slots=True)
class ImportedSymbol:
    """Describe one statically imported symbol available in a source module.

    :param module_name: Fully qualified imported module name, when known.
    :param object_name: Imported symbol name within that module.
    :param path: Resolved Python source path for the imported module, when
        available.
    """

    module_name: str | None
    object_name: str
    path: Path | None = None


@dataclass(frozen=True, slots=True)
class SourceModule:
    """Represent one parsed Python source module.

    :param path: Filesystem path containing the module source.
    :param module_name: Importable module name, when known.
    :param tree: Parsed module AST.
    :param public_names: Deterministic export names for the module.
    :param functions: Top-level function definitions keyed by local name.
    :param classes: Top-level class definitions keyed by local name.
    :param imported_symbols: Imported symbols keyed by the local alias.
    :param module_aliases: Imported module aliases keyed by the local alias.
    """

    path: Path
    module_name: str | None
    tree: ast.Module
    public_names: tuple[str, ...]
    functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = field(default_factory=dict)
    classes: dict[str, ast.ClassDef] = field(default_factory=dict)
    imported_symbols: dict[str, ImportedSymbol] = field(default_factory=dict)
    module_aliases: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DiscoveredPythonTool:
    """Describe one statically discovered Python tool candidate.

    :param tool: Generated manifest entry.
    :param binding_module_name: Importable module used for lazy runtime
        resolution.
    :param binding_file_path: Source file used for lazy runtime resolution.
    :param binding_qualname: Fully qualified object name within the module.
    """

    tool: ToolManifest
    binding_module_name: str | None = None
    binding_file_path: str | None = None
    binding_qualname: str = ""


@dataclass(frozen=True, slots=True)
class ResolvedFunction:
    """Represent one exported function resolved from a parsed source tree.

    :param export_name: Public name exposed by the target module.
    :param module: Parsed source module that defines the callable.
    :param function_node: AST node for the underlying function definition.
    """

    export_name: str
    module: SourceModule
    function_node: ast.FunctionDef | ast.AsyncFunctionDef

    @property
    def qualname(self) -> str:
        """Return the function qualname used for runtime binding."""
        return self.function_node.name


class StaticPythonResolver:
    """Discover Python tools from source files without importing user code."""

    def __init__(self) -> None:
        """Initialize deterministic source caches."""
        self._module_cache: dict[tuple[Path, str | None], SourceModule] = {}
        self._class_schema_cache: dict[tuple[Path, str | None, str], dict[str, Any]] = {}

    def discover_file(self, path: Path) -> list[DiscoveredPythonTool]:
        """Discover tools from a Python file without importing it."""
        module = self._load_source_module(path.resolve(), None)
        return self._discover_public_tools(module)

    def discover_module(self, module_name: str) -> list[DiscoveredPythonTool]:
        """Discover tools from a source-backed importable module or package."""
        path = find_module_source_path(module_name)
        if path is None:
            raise ImportError(
                f"Source-backed discovery could not locate module {module_name!r}. "
                "Use explicit callables or opt into import-based discovery for "
                "opaque extension modules."
            )
        module = self._load_source_module(path, module_name)
        return self._discover_public_tools(module)

    def _discover_public_tools(self, module: SourceModule) -> list[DiscoveredPythonTool]:
        """Build manifest entries for the module's public exported functions."""
        discovered: list[DiscoveredPythonTool] = []
        for export_name in module.public_names:
            resolved = self._resolve_export(module, export_name, seen=set())
            if resolved is None:
                continue
            discovered.append(self._build_tool_manifest(resolved))
        return discovered

    def _load_source_module(self, path: Path, module_name: str | None) -> SourceModule:
        """Parse one source module and memoize its deterministic structure."""
        cache_key = (path, module_name)
        if cache_key in self._module_cache:
            return self._module_cache[cache_key]
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
        classes: dict[str, ast.ClassDef] = {}
        imported_symbols: dict[str, ImportedSymbol] = {}
        module_aliases: dict[str, str] = {}
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions[node.name] = node
                continue
            if isinstance(node, ast.ClassDef):
                classes[node.name] = node
                continue
            if isinstance(node, ast.Import):
                for alias in node.names:
                    local_name = alias.asname or alias.name.split(".", 1)[0]
                    module_aliases[local_name] = alias.name
                continue
            if isinstance(node, ast.ImportFrom):
                imported_module_name, imported_path = self._resolve_import_from(
                    module_name,
                    path,
                    node,
                )
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    local_name = alias.asname or alias.name
                    imported_symbols[local_name] = ImportedSymbol(
                        module_name=imported_module_name,
                        object_name=alias.name,
                        path=imported_path,
                    )
        source_module = SourceModule(
            path=path,
            module_name=module_name,
            tree=tree,
            public_names=_public_names_from_ast(tree),
            functions=functions,
            classes=classes,
            imported_symbols=imported_symbols,
            module_aliases=module_aliases,
        )
        self._module_cache[cache_key] = source_module
        return source_module

    def _resolve_import_from(
        self,
        module_name: str | None,
        path: Path,
        node: ast.ImportFrom,
    ) -> tuple[str | None, Path | None]:
        """Resolve one ``from ... import ...`` statement without importing it."""
        if node.level == 0:
            if node.module is None:
                return None, None
            imported_module_name = node.module
        else:
            package_name = _package_name_for(path, module_name)
            if package_name is None:
                return None, None
            relative_name = "." * node.level + (node.module or "")
            imported_module_name = importlib.util.resolve_name(relative_name, package_name)
        return imported_module_name, find_module_source_path(imported_module_name)

    def _resolve_export(
        self,
        module: SourceModule,
        export_name: str,
        *,
        seen: set[tuple[Path, str]],
    ) -> ResolvedFunction | None:
        """Resolve one exported name to the underlying source function."""
        if export_name in module.functions:
            return ResolvedFunction(
                export_name=export_name,
                module=module,
                function_node=module.functions[export_name],
            )
        imported = module.imported_symbols.get(export_name)
        if imported is None or imported.path is None:
            return None
        cycle_key = (imported.path, imported.object_name)
        if cycle_key in seen:
            return None
        imported_module = self._load_source_module(imported.path, imported.module_name)
        resolved = self._resolve_export(
            imported_module,
            imported.object_name,
            seen={*seen, cycle_key},
        )
        if resolved is None:
            return None
        return ResolvedFunction(
            export_name=export_name,
            module=resolved.module,
            function_node=resolved.function_node,
        )

    def _build_tool_manifest(self, resolved: ResolvedFunction) -> DiscoveredPythonTool:
        """Translate one resolved source function into a manifest entry."""
        node = resolved.function_node
        docstring = parse_docstring(ast.get_docstring(node))
        input_schema = self._build_input_schema(resolved.module, node, docstring)
        output_schema = (
            self._schema_from_annotation_node(resolved.module, node.returns)
            if node.returns is not None
            else None
        )
        annotations = ToolAnnotations(
            read_only=_optional_bool(docstring.mcp_metadata.get("read_only")),
            destructive=_optional_bool(docstring.mcp_metadata.get("destructive")),
            idempotent=_optional_bool(docstring.mcp_metadata.get("idempotent")),
            open_world=_optional_bool(docstring.mcp_metadata.get("open_world")),
        )
        tool_name = _optional_str(docstring.mcp_metadata.get("name")) or resolved.export_name
        tool = ToolManifest(
            name=tool_name,
            title=_optional_str(docstring.mcp_metadata.get("title")),
            description=docstring.summary or f"Execute {resolved.export_name.replace('_', ' ')}.",
            input_schema=input_schema,
            output_schema=output_schema,
            annotations=annotations,
            source=_source_reference_for_module(resolved.module, resolved.qualname),
            binding_kind="python",
        )
        if bool(docstring.mcp_metadata.get("hidden", False)):
            raise ValueError(f"Tool {tool.name!r} is hidden by docstring metadata.")
        return DiscoveredPythonTool(
            tool=tool,
            binding_module_name=resolved.module.module_name,
            binding_file_path=(
                None if resolved.module.module_name is not None else str(resolved.module.path)
            ),
            binding_qualname=resolved.qualname,
        )

    def _build_input_schema(
        self,
        module: SourceModule,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        docstring: Any,
    ) -> dict[str, Any]:
        """Build JSON Schema for a parsed source function signature."""
        if node.args.posonlyargs:
            raise SchemaGenerationError("Positional-only parameters are not supported.")
        if node.args.vararg is not None:
            raise SchemaGenerationError("*args parameters are not supported.")
        if node.args.kwarg is not None:
            raise SchemaGenerationError("**kwargs parameters are not supported.")

        defaults = _parameter_defaults(node)
        properties: dict[str, Any] = {}
        required: list[str] = []
        for argument in [*node.args.args, *node.args.kwonlyargs]:
            if argument.annotation is None:
                raise SchemaGenerationError(
                    f"Missing type annotation for parameter {argument.arg!r}."
                )
            schema = self._schema_from_annotation_node(module, argument.annotation)
            if argument.arg in docstring.param_descriptions:
                schema["description"] = docstring.param_descriptions[argument.arg]
            default_node = defaults.get(argument.arg)
            if default_node is None:
                required.append(argument.arg)
            else:
                with contextlib.suppress(SchemaGenerationError, TypeError):
                    schema["default"] = to_json_compatible(
                        self._literal_value(module, default_node)
                    )
            properties[argument.arg] = schema
        input_schema: dict[str, Any] = {"type": "object", "properties": properties}
        if required:
            input_schema["required"] = required
        return input_schema

    def _schema_from_annotation_node(
        self,
        module: SourceModule,
        annotation: ast.AST | None,
    ) -> dict[str, Any]:
        """Build JSON Schema directly from a source annotation AST node."""
        if annotation is None:
            raise SchemaGenerationError("Missing type annotation.")
        if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
            return {
                "anyOf": [
                    self._schema_from_annotation_node(module, annotation.left),
                    self._schema_from_annotation_node(module, annotation.right),
                ]
            }
        if isinstance(annotation, ast.Constant) and annotation.value is None:
            return {"type": "null"}
        if isinstance(annotation, ast.Subscript):
            return self._schema_from_subscript(module, annotation)
        canonical_name = _annotation_name(module, annotation)
        if canonical_name is None:
            raise SchemaGenerationError(f"Unsupported annotation: {ast.unparse(annotation)!r}")
        primitive = _PRIMITIVE_SCHEMAS.get(canonical_name)
        if primitive is not None:
            return dict(primitive)
        if canonical_name in _ANY_NAMES:
            return {}
        if canonical_name in _PATH_NAMES:
            return {
                "type": "string",
                "format": "path",
                "x-mcpcraft-kind": "path",
                "x-mcpcraft-path-kind": "auto",
            }
        if canonical_name in _PATHLIKE_NAMES:
            return {
                "type": "string",
                "format": "path",
                "x-mcpcraft-kind": "path",
                "x-mcpcraft-path-kind": "auto",
            }
        if canonical_name in _BYTES_NAMES:
            return {
                "type": "string",
                "contentEncoding": "base64",
                "x-mcpcraft-kind": "bytes",
            }
        if canonical_name in _NDARRAY_NAMES:
            return {"type": "array", "items": {"type": "number"}}
        resolved_class = self._resolve_class_node(module, canonical_name, seen=set())
        if resolved_class is not None:
            resolved_module, resolved_name, class_node = resolved_class
            return self._schema_from_class(resolved_module, class_node, resolved_name)
        raise SchemaGenerationError(f"Unsupported annotation: {canonical_name!r}")

    def _schema_from_subscript(
        self,
        module: SourceModule,
        annotation: ast.Subscript,
    ) -> dict[str, Any]:
        """Build JSON Schema for generic-like source annotations."""
        container_name = _annotation_name(module, annotation.value)
        arguments = _subscript_arguments(annotation)
        if container_name in _LIST_NAMES | _TUPLE_NAMES | _SET_NAMES | _SEQUENCE_NAMES:
            item_annotation = arguments[0] if arguments else None
            schema: dict[str, Any] = {
                "type": "array",
                "items": self._schema_from_annotation_node(module, item_annotation),
            }
            if container_name in _SET_NAMES:
                schema["uniqueItems"] = True
            return schema
        if container_name in _DICT_NAMES | _MAPPING_NAMES:
            if len(arguments) != 2:
                raise SchemaGenerationError("dict annotations must include key and value types.")
            key_name = _annotation_name(module, arguments[0])
            if key_name != "str":
                raise SchemaGenerationError("Only dict[str, T] is supported.")
            return {
                "type": "object",
                "additionalProperties": self._schema_from_annotation_node(module, arguments[1]),
            }
        if container_name in _PATHLIKE_NAMES:
            return {
                "type": "string",
                "format": "path",
                "x-mcpcraft-kind": "path",
                "x-mcpcraft-path-kind": "auto",
            }
        if container_name in _UNION_NAMES:
            return {
                "anyOf": [self._schema_from_annotation_node(module, item) for item in arguments]
            }
        if container_name in _OPTIONAL_NAMES:
            if len(arguments) != 1:
                raise SchemaGenerationError(
                    "Optional annotations must contain exactly one value type."
                )
            return {
                "anyOf": [
                    self._schema_from_annotation_node(module, arguments[0]),
                    {"type": "null"},
                ]
            }
        if container_name in _LITERAL_NAMES:
            values = [self._literal_value(module, item) for item in arguments]
            return {"type": _infer_literal_type(values), "enum": values}
        if container_name in _ANNOTATED_NAMES:
            if not arguments:
                raise SchemaGenerationError("Annotated annotations must include a wrapped type.")
            base_schema = self._schema_from_annotation_node(module, arguments[0])
            return _apply_annotation_metadata(
                base_schema,
                [self._literal_value(module, item) for item in arguments[1:]],
            )
        if container_name in _NDARRAY_NAMES:
            return {"type": "array", "items": {"type": "number"}}
        raise SchemaGenerationError(f"Unsupported annotation: {ast.unparse(annotation)!r}")

    def _resolve_class_node(
        self,
        module: SourceModule,
        class_name: str,
        *,
        seen: set[tuple[Path, str]],
    ) -> tuple[SourceModule, str, ast.ClassDef] | None:
        """Resolve one class annotation across same-package re-exports."""
        if class_name in module.classes:
            return module, class_name, module.classes[class_name]
        imported = module.imported_symbols.get(class_name)
        if imported is None or imported.path is None:
            return None
        cycle_key = (imported.path, imported.object_name)
        if cycle_key in seen:
            return None
        imported_module = self._load_source_module(imported.path, imported.module_name)
        return self._resolve_class_node(
            imported_module,
            imported.object_name,
            seen={*seen, cycle_key},
        )

    def _schema_from_class(
        self,
        module: SourceModule,
        class_node: ast.ClassDef,
        class_name: str,
    ) -> dict[str, Any]:
        """Build JSON Schema for a source-defined dataclass, enum, or TypedDict."""
        cache_key = (module.path, module.module_name, class_name)
        if cache_key in self._class_schema_cache:
            return dict(self._class_schema_cache[cache_key])
        if _is_enum_class(module, class_node):
            values = [
                self._literal_value(module, assign.value)
                for assign in class_node.body
                if isinstance(assign, ast.Assign)
                and len(assign.targets) == 1
                and isinstance(assign.targets[0], ast.Name)
                and not assign.targets[0].id.startswith("_")
            ]
            schema = {"type": _infer_literal_type(values), "enum": values}
            self._class_schema_cache[cache_key] = schema
            return dict(schema)
        if _is_typed_dict_class(module, class_node):
            schema = self._schema_from_typed_dict(module, class_node)
            self._class_schema_cache[cache_key] = schema
            return dict(schema)
        if _is_dataclass_class(module, class_node):
            schema = self._schema_from_dataclass(module, class_node)
            self._class_schema_cache[cache_key] = schema
            return dict(schema)
        raise SchemaGenerationError(f"Unsupported class annotation: {class_name!r}")

    def _schema_from_typed_dict(
        self,
        module: SourceModule,
        class_node: ast.ClassDef,
    ) -> dict[str, Any]:
        """Build JSON Schema for a source-defined ``TypedDict`` class."""
        properties: dict[str, Any] = {}
        required: list[str] = []
        total = True
        for keyword in class_node.keywords:
            if keyword.arg == "total" and isinstance(keyword.value, ast.Constant):
                total = bool(keyword.value.value)
        for child in class_node.body:
            if not isinstance(child, ast.AnnAssign) or not isinstance(child.target, ast.Name):
                continue
            properties[child.target.id] = self._schema_from_annotation_node(
                module,
                child.annotation,
            )
            if total:
                required.append(child.target.id)
        result_schema: dict[str, Any] = {"type": "object", "properties": properties}
        if required:
            result_schema["required"] = required
        return result_schema

    def _schema_from_dataclass(
        self,
        module: SourceModule,
        class_node: ast.ClassDef,
    ) -> dict[str, Any]:
        """Build JSON Schema for a source-defined dataclass."""
        properties: dict[str, Any] = {}
        required: list[str] = []
        for child in class_node.body:
            if not isinstance(child, ast.AnnAssign) or not isinstance(child.target, ast.Name):
                continue
            schema = self._schema_from_annotation_node(module, child.annotation)
            if child.value is None:
                required.append(child.target.id)
            else:
                schema["default"] = to_json_compatible(self._literal_value(module, child.value))
            properties[child.target.id] = schema
        result_schema: dict[str, Any] = {"type": "object", "properties": properties}
        if required:
            result_schema["required"] = required
        return result_schema

    def _literal_value(self, module: SourceModule, node: ast.AST) -> Any:
        """Evaluate one supported literal AST node deterministically."""
        try:
            return ast.literal_eval(node)
        except Exception:
            pass
        if isinstance(node, ast.Attribute):
            base_name = _annotation_name(module, node.value)
            if base_name is not None and base_name in module.classes:
                class_node = module.classes[base_name]
                if _is_enum_class(module, class_node):
                    for assign in class_node.body:
                        if (
                            isinstance(assign, ast.Assign)
                            and len(assign.targets) == 1
                            and isinstance(assign.targets[0], ast.Name)
                            and assign.targets[0].id == node.attr
                        ):
                            return self._literal_value(module, assign.value)
            imported = module.imported_symbols.get(base_name) if base_name is not None else None
            if imported is not None and imported.path is not None:
                imported_module = self._load_source_module(imported.path, imported.module_name)
                imported_class = imported_module.classes.get(imported.object_name)
                if imported_class is not None and _is_enum_class(imported_module, imported_class):
                    for assign in imported_class.body:
                        if (
                            isinstance(assign, ast.Assign)
                            and len(assign.targets) == 1
                            and isinstance(assign.targets[0], ast.Name)
                            and assign.targets[0].id == node.attr
                        ):
                            return self._literal_value(imported_module, assign.value)
        if isinstance(node, ast.Call):
            call_name = _annotation_name(module, node.func)
            if call_name in _PATH_NAMES and len(node.args) == 1 and not node.keywords:
                return str(self._literal_value(module, node.args[0]))
            if call_name == "_resolve_symbol" and len(node.args) == 2 and not node.keywords:
                module_argument = node.args[0]
                qualname_argument = node.args[1]
                if not isinstance(module_argument, ast.Constant) or not isinstance(
                    qualname_argument, ast.Constant
                ):
                    raise SchemaGenerationError(
                        "Generated _resolve_symbol defaults must use constant string arguments."
                    )
                module_name = module_argument.value
                qualname = qualname_argument.value
                if isinstance(module_name, str) and isinstance(qualname, str):
                    return self._resolved_symbol_literal(module, module_name, qualname)
        raise SchemaGenerationError(
            "Source-backed discovery supports only literal defaults and enum/path literals."
        )

    def _resolved_symbol_literal(
        self,
        module: SourceModule,
        module_name: str,
        qualname: str,
    ) -> Any:
        """Resolve supported generated ``_resolve_symbol`` literals without imports."""
        del module
        source_path = find_module_source_path(module_name)
        if source_path is None:
            raise SchemaGenerationError(f"Could not locate source for {module_name!r}.")
        source_module = self._load_source_module(source_path, module_name)
        parts = qualname.split(".")
        if len(parts) == 2 and parts[0] in source_module.classes:
            class_node = source_module.classes[parts[0]]
            if _is_enum_class(source_module, class_node):
                for assign in class_node.body:
                    if (
                        isinstance(assign, ast.Assign)
                        and len(assign.targets) == 1
                        and isinstance(assign.targets[0], ast.Name)
                        and assign.targets[0].id == parts[1]
                    ):
                        return self._literal_value(source_module, assign.value)
        raise SchemaGenerationError(
            "Generated symbol defaults are only supported for enum member literals."
        )


def _annotation_name(module: SourceModule, node: ast.AST) -> str | None:
    """Return the deterministic dotted name for a source annotation node."""
    if isinstance(node, ast.Name):
        return module.module_aliases.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        base_name = _annotation_name(module, node.value)
        if base_name is None:
            return None
        return f"{base_name}.{node.attr}"
    return None


def _parameter_defaults(node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, ast.AST | None]:
    """Map source parameters to their default AST nodes, when present."""
    defaults: dict[str, ast.AST | None] = {}
    positional_arguments = list(node.args.args)
    positional_defaults: list[ast.AST | None] = [None] * (
        len(positional_arguments) - len(node.args.defaults)
    )
    positional_defaults.extend(node.args.defaults)
    for argument, default in zip(positional_arguments, positional_defaults, strict=True):
        defaults[argument.arg] = default
    for argument, default in zip(node.args.kwonlyargs, node.args.kw_defaults, strict=True):
        defaults[argument.arg] = default
    return defaults


def _subscript_arguments(annotation: ast.Subscript) -> list[ast.AST]:
    """Normalize the subscript argument list across Python AST shapes."""
    if isinstance(annotation.slice, ast.Tuple):
        return list(annotation.slice.elts)
    return [annotation.slice]


def _is_dataclass_class(module: SourceModule, class_node: ast.ClassDef) -> bool:
    """Return whether the class is decorated as a dataclass."""
    return any(
        (_annotation_name(module, decorator) or "") in _DATACLASS_DECORATORS
        for decorator in class_node.decorator_list
    )


def _is_enum_class(module: SourceModule, class_node: ast.ClassDef) -> bool:
    """Return whether the class derives from ``Enum``."""
    return any((_annotation_name(module, base) or "") in _ENUM_NAMES for base in class_node.bases)


def _is_typed_dict_class(module: SourceModule, class_node: ast.ClassDef) -> bool:
    """Return whether the class derives from ``TypedDict``."""
    return any(
        (_annotation_name(module, base) or "") in _TYPED_DICT_NAMES for base in class_node.bases
    )


def _apply_annotation_metadata(schema: dict[str, Any], metadata: list[Any]) -> dict[str, Any]:
    """Apply deterministic ``Annotated`` metadata to a generated schema."""
    updated = dict(schema)
    for item in metadata:
        if isinstance(item, str):
            if updated.get("format") == "path" and item in {"file", "directory", "auto"}:
                updated["x-mcpcraft-path-kind"] = item
            if updated.get("x-mcpcraft-kind") == "bytes" and item == "binary":
                updated["x-mcpcraft-bytes-kind"] = "binary"
            continue
        if (
            isinstance(item, dict)
            and updated.get("format") == "path"
            and item.get("kind") in {"file", "directory", "auto"}
        ):
            updated["x-mcpcraft-path-kind"] = item["kind"]
    return updated


def _infer_literal_type(values: list[Any]) -> str:
    """Infer a JSON Schema primitive type from literal values."""
    if all(isinstance(value, bool) for value in values):
        return "boolean"
    if all(isinstance(value, int) and not isinstance(value, bool) for value in values):
        return "integer"
    if all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in values):
        return "number"
    return "string"


def _public_names_from_ast(module: ast.Module) -> tuple[str, ...]:
    """Return deterministic public export names from a parsed source tree."""
    for node in module.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    values = _literal_str_sequence(node.value)
                    if values is not None:
                        return tuple(values)
    public_names = [
        node.name
        for node in module.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and not node.name.startswith("_")
    ]
    return tuple(sorted(public_names))


def _literal_str_sequence(node: ast.AST) -> tuple[str, ...] | None:
    """Extract a literal string list or tuple from an AST node."""
    if not isinstance(node, (ast.List, ast.Tuple)):
        return None
    values: list[str] = []
    for element in node.elts:
        if not isinstance(element, ast.Constant) or not isinstance(element.value, str):
            return None
        values.append(element.value)
    return tuple(values)


def _source_reference_for_module(module: SourceModule, qualname: str) -> SourceReference:
    """Build a stable source reference for one parsed callable."""
    if module.module_name is not None:
        return SourceReference(
            kind="module",
            target=module.module_name,
            location=f"{module.module_name}.{qualname}",
        )
    return SourceReference(
        kind="file",
        target=str(module.path),
        location=f"{module.path}:{qualname}",
    )


def _package_name_for(path: Path, module_name: str | None) -> str | None:
    """Return the import package name used for relative import resolution."""
    if module_name is None:
        return None
    if path.name == "__init__.py":
        return module_name
    if "." not in module_name:
        return module_name
    return module_name.rsplit(".", 1)[0]


def _optional_bool(value: object) -> bool | None:
    """Return a boolean value or ``None``."""
    return value if isinstance(value, bool) else None


def _optional_str(value: object) -> str | None:
    """Return a string value or ``None``."""
    return value if isinstance(value, str) else None


def find_module_source_path(module_name: str) -> Path | None:
    """Resolve the source path for an importable Python module without importing it."""
    spec = importlib.util.find_spec(module_name)
    if spec is None or spec.origin is None:
        return None
    origin = Path(spec.origin)
    if origin.suffix != ".py":
        return None
    return origin.resolve()


def load_module_from_path(path: Path, *, fresh: bool = False) -> ModuleType:
    """Import a Python file under a synthetic module name.

    ``fresh=True`` uses the file contents in the synthetic module name so edits
    invalidate the cache deterministically.
    """
    resolved_path = path.resolve()
    path_hash = hashlib.sha256(str(resolved_path).encode("utf-8")).hexdigest()[:12]
    if fresh:
        content_hash = hashlib.sha256(resolved_path.read_bytes()).hexdigest()[:12]
        module_name = f"_mcpcraft_dynamic_{resolved_path.stem}_{path_hash}_{content_hash}"
    else:
        module_name = f"_mcpcraft_dynamic_{resolved_path.stem}_{path_hash}"
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, resolved_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load module from {resolved_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    with _temporary_sys_path(resolved_path.parent):
        spec.loader.exec_module(module)
    return module


def resolve_qualname(module: ModuleType, qualname: str) -> Any:
    """Resolve a dotted qualname against an imported module object."""
    if "<locals>" in qualname:
        raise ValueError("Local function qualnames are not supported for lazy loading.")
    target: Any = module
    for segment in qualname.split("."):
        target = getattr(target, segment)
    return target


@contextlib.contextmanager
def _temporary_sys_path(path: Path) -> Iterator[None]:
    """Temporarily prepend a path to ``sys.path`` while importing a file."""
    sys.path.insert(0, str(path))
    try:
        yield
    finally:
        with contextlib.suppress(ValueError):
            sys.path.remove(str(path))

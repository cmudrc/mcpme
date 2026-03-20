"""Deterministic facade generation for installed packages and CLI tools.

The generated facade files are intentionally plain Python modules. ``mcpcraft``
already knows how to discover and serve Python callables well, so the most
general ingestion move is to translate foreign surfaces into a small wrapper
module and then let normal discovery take over.

This module keeps that translation deterministic:

- installed Python packages become generated facade functions,
- public classes become session-oriented facade functions,
- CLI tools become generated subprocess wrapper callables, and
- every generated wrapper includes docstrings that preserve the original source
  path and signature text.
"""

from __future__ import annotations

import importlib
import inspect
import json
import os
import pkgutil
import re
import sys
import types
from collections import abc
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Annotated, Any, Union, get_args, get_origin

from .docstrings import parse_docstring

_DEFAULT_MISSING = object()


@dataclass(frozen=True, slots=True)
class ScaffoldedTool:
    """Describe one generated facade tool."""

    name: str
    kind: str
    style: str
    source: str

    def to_dict(self) -> dict[str, str]:
        """Return a JSON-compatible representation."""
        return {
            "name": self.name,
            "kind": self.kind,
            "style": self.style,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class SkippedScaffoldEntry:
    """Describe one symbol skipped during ingestion."""

    source: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        """Return a JSON-compatible representation."""
        return {"source": self.source, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class ScaffoldReport:
    """Summarize one scaffold generation run."""

    target_kind: str
    target: str
    output_path: Path
    modules_inspected: tuple[str, ...]
    generated_tools: tuple[ScaffoldedTool, ...]
    skipped: tuple[SkippedScaffoldEntry, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation."""
        return {
            "targetKind": self.target_kind,
            "target": self.target,
            "outputPath": str(self.output_path),
            "modulesInspected": list(self.modules_inspected),
            "generatedTools": [tool.to_dict() for tool in self.generated_tools],
            "skipped": [entry.to_dict() for entry in self.skipped],
        }


@dataclass(frozen=True, slots=True)
class _FunctionSpec:
    """Describe one generated wrapper around a Python callable."""

    name: str
    module_name: str
    qualname: str
    summary: str
    signature_text: str
    param_descriptions: dict[str, str]
    style: str
    parameters: tuple[inspect.Parameter, ...] = ()

    @property
    def source(self) -> str:
        """Return the fully qualified import path for the wrapped callable."""
        return f"{self.module_name}.{self.qualname}"


@dataclass(frozen=True, slots=True)
class _ClassSpec:
    """Describe one generated session facade for a public class."""

    create_name: str
    close_name: str
    class_name: str
    module_name: str
    qualname: str
    summary: str
    constructor_signature_text: str
    constructor_param_descriptions: dict[str, str]
    constructor_style: str
    constructor_parameters: tuple[inspect.Parameter, ...]
    method_specs: tuple[_FunctionSpec, ...]

    @property
    def source(self) -> str:
        """Return the fully qualified import path for the wrapped class."""
        return f"{self.module_name}.{self.qualname}"


@dataclass(frozen=True, slots=True)
class _CliParameter:
    """Describe one generated parameter inferred from CLI help text."""

    name: str
    positional: bool
    syntax: str
    emitted_option: str | None
    annotation_source: str
    required: bool
    default_source: str | None
    description: str
    takes_value: bool
    inverted_boolean: bool = False


def scaffold_package(
    package_name: str,
    output_path: Path,
    *,
    include_submodules: bool = False,
    max_modules: int | None = None,
    max_generated_tools: int | None = None,
    module_include_patterns: tuple[str, ...] = (),
    module_exclude_patterns: tuple[str, ...] = (),
    symbol_include_patterns: tuple[str, ...] = (),
    symbol_exclude_patterns: tuple[str, ...] = (),
    allow_reexports: bool = False,
) -> ScaffoldReport:
    """Generate a deterministic facade module for an importable package or module."""
    namespace_root = package_name.split(".", 1)[0]
    module_includes = _compile_patterns(module_include_patterns)
    module_excludes = _compile_patterns(module_exclude_patterns)
    symbol_includes = _compile_patterns(symbol_include_patterns)
    symbol_excludes = _compile_patterns(symbol_exclude_patterns)
    module_names, skipped = _discover_module_names(
        package_name,
        include_submodules=include_submodules,
        max_modules=max_modules,
        include_patterns=module_includes,
        exclude_patterns=module_excludes,
    )
    function_specs: list[_FunctionSpec] = []
    class_specs: list[_ClassSpec] = []
    seen_sources: set[str] = set()
    generated_tool_count = 0
    for module_name in module_names:
        module = importlib.import_module(module_name)
        for export_name in _public_member_names(module):
            if not _matches_patterns(export_name, symbol_includes, symbol_excludes):
                skipped.append(
                    SkippedScaffoldEntry(
                        source=f"{module_name}.{export_name}",
                        reason="symbol name excluded by scaffold filters",
                    )
                )
                continue
            try:
                obj = getattr(module, export_name)
            except Exception as error:
                skipped.append(
                    SkippedScaffoldEntry(
                        source=f"{module_name}.{export_name}",
                        reason=f"attribute access failed: {error}",
                    )
                )
                continue
            if inspect.isclass(obj):
                class_source = f"{obj.__module__}.{obj.__qualname__}"
                if not allow_reexports and not _within_namespace(obj.__module__, namespace_root):
                    skipped.append(
                        SkippedScaffoldEntry(
                            source=f"{module_name}.{export_name}",
                            reason="class is re-exported from outside the target namespace",
                        )
                    )
                    continue
                if _skip_class(obj):
                    skipped.append(
                        SkippedScaffoldEntry(
                            source=f"{module_name}.{export_name}",
                            reason=("class is internal or not useful for generic session wrapping"),
                        )
                    )
                    continue
                if class_source in seen_sources:
                    continue
                estimated_tools = 2 + sum(
                    1
                    for _, raw_member in _iter_public_instance_methods(obj, namespace_root)
                    if inspect.isfunction(raw_member)
                )
                if (
                    max_generated_tools is not None
                    and generated_tool_count + estimated_tools > max_generated_tools
                ):
                    skipped.append(
                        SkippedScaffoldEntry(
                            source=f"{module_name}.{export_name}",
                            reason="class wrappers would exceed max_generated_tools",
                        )
                    )
                    continue
                seen_sources.add(class_source)
                try:
                    class_spec = _class_spec_for(
                        context_module_name=module_name,
                        export_name=export_name,
                        cls=obj,
                        package_name=package_name,
                        namespace_root=namespace_root,
                    )
                    class_specs.append(class_spec)
                    generated_tool_count += 2 + len(class_spec.method_specs)
                except (TypeError, ValueError) as error:
                    skipped.append(
                        SkippedScaffoldEntry(
                            source=f"{module_name}.{export_name}",
                            reason=f"class signature inspection failed: {error}",
                        )
                    )
                continue
            if not callable(obj):
                continue
            object_module = getattr(obj, "__module__", module_name)
            object_qualname = getattr(obj, "__qualname__", export_name)
            function_source = f"{object_module}.{object_qualname}"
            if not allow_reexports and not _within_namespace(object_module, namespace_root):
                skipped.append(
                    SkippedScaffoldEntry(
                        source=f"{module_name}.{export_name}",
                        reason="function is re-exported from outside the target namespace",
                    )
                )
                continue
            if max_generated_tools is not None and generated_tool_count >= max_generated_tools:
                skipped.append(
                    SkippedScaffoldEntry(
                        source=f"{module_name}.{export_name}",
                        reason="function wrappers would exceed max_generated_tools",
                    )
                )
                continue
            if function_source in seen_sources:
                continue
            try:
                signature = inspect.signature(obj)
            except (TypeError, ValueError) as error:
                skipped.append(
                    SkippedScaffoldEntry(
                        source=f"{module_name}.{export_name}",
                        reason=f"signature inspection failed: {error}",
                    )
                )
                continue
            seen_sources.add(function_source)
            function_specs.append(
                _function_spec_for(
                    context_module_name=module_name,
                    export_name=export_name,
                    obj=obj,
                    signature=signature,
                    package_name=package_name,
                )
            )
            generated_tool_count += 1
    content = _render_package_facade(
        package_name,
        function_specs=tuple(function_specs),
        class_specs=tuple(class_specs),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")

    generated_tools: list[ScaffoldedTool] = []
    for spec in function_specs:
        generated_tools.append(
            ScaffoldedTool(
                name=spec.name,
                kind="function",
                style=spec.style,
                source=spec.source,
            )
        )
    for class_spec in class_specs:
        generated_tools.append(
            ScaffoldedTool(
                name=class_spec.create_name,
                kind="class_create",
                style=class_spec.constructor_style,
                source=class_spec.source,
            )
        )
        for method_spec in class_spec.method_specs:
            generated_tools.append(
                ScaffoldedTool(
                    name=method_spec.name,
                    kind="class_method",
                    style=method_spec.style,
                    source=method_spec.source,
                )
            )
        generated_tools.append(
            ScaffoldedTool(
                name=class_spec.close_name,
                kind="class_close",
                style="named",
                source=class_spec.source,
            )
        )

    return ScaffoldReport(
        target_kind="package",
        target=package_name,
        output_path=output_path,
        modules_inspected=tuple(module_names),
        generated_tools=tuple(generated_tools),
        skipped=tuple(skipped),
    )


def scaffold_command(
    command: tuple[str, ...],
    output_path: Path,
    *,
    function_name: str | None = None,
    help_timeout_seconds: float = 5.0,
    help_probe_args: tuple[str, ...] = ("--help",),
) -> ScaffoldReport:
    """Generate a deterministic facade module for one CLI command."""
    if not command:
        raise ValueError("scaffold_command requires at least one command token.")
    resolved_name = function_name or f"run_{_sanitize_name(Path(command[0]).name)}"
    help_text = _capture_help_text(
        command,
        timeout_seconds=help_timeout_seconds,
        help_probe_args=help_probe_args,
    )
    parameters = _parse_command_parameters(help_text or "")
    content = _render_command_facade(
        command=command,
        function_name=resolved_name,
        help_text=help_text,
        parameters=parameters,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")

    skipped: tuple[SkippedScaffoldEntry, ...] = ()
    if help_text is None:
        skipped = (
            SkippedScaffoldEntry(
                source=" ".join(command),
                reason="help capture failed; generated argv passthrough wrapper",
            ),
        )
    elif not parameters:
        skipped = (
            SkippedScaffoldEntry(
                source=" ".join(command),
                reason=(
                    "help text did not yield stable parameters; generated argv passthrough wrapper"
                ),
            ),
        )

    return ScaffoldReport(
        target_kind="command",
        target=" ".join(command),
        output_path=output_path,
        modules_inspected=(),
        generated_tools=(
            ScaffoldedTool(
                name=resolved_name,
                kind="command",
                style="named" if parameters else "argv",
                source=" ".join(command),
            ),
        ),
        skipped=skipped,
    )


def _discover_module_names(
    package_name: str,
    *,
    include_submodules: bool,
    max_modules: int | None,
    include_patterns: tuple[re.Pattern[str], ...] = (),
    exclude_patterns: tuple[re.Pattern[str], ...] = (),
) -> tuple[list[str], list[SkippedScaffoldEntry]]:
    """Return importable module names inspected for package scaffolding."""
    root_module = importlib.import_module(package_name)
    module_names = []
    skipped: list[SkippedScaffoldEntry] = []
    if _matches_patterns(package_name, include_patterns, exclude_patterns):
        module_names.append(package_name)
    else:
        skipped.append(
            SkippedScaffoldEntry(
                source=package_name,
                reason="module name excluded by scaffold filters",
            )
        )
    if not include_submodules or not hasattr(root_module, "__path__"):
        return module_names, skipped
    walked = sorted(
        pkgutil.walk_packages(root_module.__path__, prefix=f"{package_name}."),
        key=lambda module_info: module_info.name,
    )
    for module_info in walked:
        if any(part.startswith("_") for part in module_info.name.split(".")[1:]):
            skipped.append(
                SkippedScaffoldEntry(
                    source=module_info.name,
                    reason="submodule path is internal",
                )
            )
            continue
        if not _matches_patterns(module_info.name, include_patterns, exclude_patterns):
            skipped.append(
                SkippedScaffoldEntry(
                    source=module_info.name,
                    reason="module name excluded by scaffold filters",
                )
            )
            continue
        try:
            importlib.import_module(module_info.name)
        except Exception as error:
            skipped.append(
                SkippedScaffoldEntry(
                    source=module_info.name,
                    reason=f"submodule import failed: {error}",
                )
            )
            continue
        module_names.append(module_info.name)
        if max_modules is not None and len(module_names) >= max_modules:
            break
    return module_names, skipped


def _public_member_names(module: object) -> tuple[str, ...]:
    """Return deterministic public member names for one imported module."""
    exported_object = vars(module).get("__all__")
    if isinstance(exported_object, (list, tuple)):
        exported = tuple(name for name in exported_object if isinstance(name, str))
        return tuple(dict.fromkeys(name for name in exported if not name.startswith("_")))
    return tuple(name for name in sorted(vars(module)) if not name.startswith("_"))


def _skip_class(cls: type[object]) -> bool:
    """Return whether a class should be skipped for generic session scaffolding."""
    return issubclass(cls, BaseException)


def _function_spec_for(
    context_module_name: str,
    export_name: str,
    obj: object,
    signature: inspect.Signature,
    package_name: str,
) -> _FunctionSpec:
    """Build one generated function wrapper specification."""
    docstring = parse_docstring(inspect.getdoc(obj))
    return _FunctionSpec(
        name=_function_wrapper_name(context_module_name, export_name, package_name),
        module_name=getattr(obj, "__module__", context_module_name),
        qualname=getattr(obj, "__qualname__", export_name),
        summary=docstring.summary or f"Call {export_name}.",
        signature_text=f"{export_name}{signature}",
        param_descriptions=dict(docstring.param_descriptions),
        style="named" if _supports_named_wrapper(signature) else "args_kwargs",
        parameters=tuple(signature.parameters.values()),
    )


def _class_spec_for(
    context_module_name: str,
    export_name: str,
    cls: type[object],
    package_name: str,
    namespace_root: str,
) -> _ClassSpec:
    """Build one generated class session wrapper specification."""
    class_name = export_name
    class_snake = _camel_to_snake(class_name)
    qualifier = _module_qualifier(context_module_name, package_name)
    prefix = f"{qualifier}__" if qualifier else ""
    create_name = f"{prefix}create_{class_snake}"
    close_name = f"{prefix}close_{class_snake}"
    init_signature = inspect.signature(cls)
    init_docstring = parse_docstring(inspect.getdoc(cls.__init__))
    method_specs: list[_FunctionSpec] = []
    for method_name, raw_member in _iter_public_instance_methods(cls, namespace_root):
        method_signature = inspect.signature(raw_member)
        method_docstring = parse_docstring(inspect.getdoc(raw_member))
        stripped_signature = _drop_first_parameter(method_signature)
        method_specs.append(
            _FunctionSpec(
                name=f"{prefix}{class_snake}_{method_name}",
                module_name=getattr(raw_member, "__module__", cls.__module__),
                qualname=getattr(raw_member, "__qualname__", f"{cls.__qualname__}.{method_name}"),
                summary=method_docstring.summary or f"Call {class_name}.{method_name}.",
                signature_text=f"{method_name}{method_signature}",
                param_descriptions=dict(method_docstring.param_descriptions),
                style=("named" if _supports_named_wrapper(stripped_signature) else "args_kwargs"),
                parameters=tuple(stripped_signature.parameters.values()),
            )
        )
    class_docstring = parse_docstring(inspect.getdoc(cls))
    return _ClassSpec(
        create_name=create_name,
        close_name=close_name,
        class_name=class_name,
        module_name=cls.__module__,
        qualname=cls.__qualname__,
        summary=class_docstring.summary or f"Create a managed session for {class_name}.",
        constructor_signature_text=f"{class_name}{init_signature}",
        constructor_param_descriptions=dict(init_docstring.param_descriptions),
        constructor_style="named" if _supports_named_wrapper(init_signature) else "args_kwargs",
        constructor_parameters=tuple(init_signature.parameters.values()),
        method_specs=tuple(method_specs),
    )


def _drop_first_parameter(signature: inspect.Signature) -> inspect.Signature:
    """Return a signature without the leading instance parameter."""
    parameters = list(signature.parameters.values())
    if parameters and parameters[0].name in {"self", "cls"}:
        parameters = parameters[1:]
    return signature.replace(parameters=parameters)


def _supports_named_wrapper(signature: inspect.Signature) -> bool:
    """Return whether a direct named wrapper can be generated for a signature."""
    for parameter in signature.parameters.values():
        if parameter.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            return False
        if parameter.default is inspect.Signature.empty:
            continue
        if _default_source(parameter.default) is None:
            return False
    return True


def _iter_public_instance_methods(
    cls: type[object],
    package_name: str,
) -> tuple[tuple[str, Callable[..., Any]], ...]:
    """Return deterministic public instance methods across a class MRO."""
    seen_names: set[str] = set()
    methods: list[tuple[str, Callable[..., Any]]] = []
    for candidate_class in cls.mro():
        if candidate_class is object:
            continue
        if not _within_namespace(getattr(candidate_class, "__module__", ""), package_name):
            continue
        for method_name, raw_member in sorted(candidate_class.__dict__.items()):
            if method_name in seen_names or method_name.startswith("_") or method_name == "close":
                continue
            if isinstance(raw_member, (staticmethod, classmethod)):
                continue
            if not inspect.isfunction(raw_member):
                continue
            seen_names.add(method_name)
            methods.append((method_name, raw_member))
    return tuple(methods)


def _default_source(value: object) -> str | None:
    """Return a stable source representation for simple default values."""
    return _value_source(value)


def _function_wrapper_name(
    context_module_name: str,
    export_name: str,
    package_name: str,
) -> str:
    """Build a deterministic wrapper name for one exported function."""
    qualifier = _module_qualifier(context_module_name, package_name)
    return export_name if not qualifier else f"{qualifier}__{export_name}"


def _module_qualifier(module_name: str, package_name: str) -> str:
    """Return a deterministic module qualifier relative to the root package."""
    if module_name == package_name:
        return ""
    relative = module_name[len(package_name) + 1 :].replace(".", "__")
    return _sanitize_name(relative)


def _camel_to_snake(name: str) -> str:
    """Convert one class-like identifier into a deterministic snake-case token."""
    characters: list[str] = []
    for index, character in enumerate(name):
        if character.isupper() and index > 0 and not name[index - 1].isupper():
            characters.append("_")
        characters.append(character.lower())
    return "".join(characters)


def _sanitize_name(value: str) -> str:
    """Normalize a string into an MCP-friendly token."""
    sanitized = "".join(character if character.isalnum() else "_" for character in value)
    while "__" in sanitized:
        sanitized = sanitized.replace("__", "_")
    return sanitized.strip("_")


def _parse_command_parameters(help_text: str) -> tuple[_CliParameter, ...]:
    """Parse stable CLI parameters from help text when the format is recognizable."""
    if not help_text.strip():
        return ()
    required_options = _parse_usage_required_options(help_text)
    parameters: list[_CliParameter] = []
    seen_names: set[str] = set()
    section: str | None = None
    for raw_line in help_text.splitlines():
        stripped = raw_line.strip()
        lowered = stripped.lower()
        if not stripped:
            continue
        if lowered in {
            "options:",
            "optional arguments:",
            "flags:",
            "named arguments:",
        }:
            section = "options"
            continue
        if lowered in {
            "positional arguments:",
            "arguments:",
            "required arguments:",
        }:
            section = "positionals"
            continue
        if section is None:
            continue
        columns = _split_help_columns(raw_line)
        if columns is None:
            continue
        left, description = columns
        parameter: _CliParameter | None
        if left.startswith("-") or section == "options":
            parameter = _parse_option_parameter(
                syntax=left,
                description=description,
                required_options=required_options,
            )
        else:
            parameter = _parse_positional_parameter(left, description)
        if parameter is None or parameter.name in seen_names:
            continue
        seen_names.add(parameter.name)
        parameters.append(parameter)
    return tuple(parameters)


def _parse_usage_required_options(help_text: str) -> set[str]:
    """Return long-form option spellings that appear required in the usage line."""
    usage_line = next(
        (
            line.strip()
            for line in help_text.splitlines()
            if line.strip().lower().startswith("usage:")
        ),
        "",
    )
    if not usage_line:
        return set()
    required: set[str] = set()
    bracket_depth = 0
    for token in usage_line.split():
        bracket_depth += token.count("[")
        if token.startswith("--") and bracket_depth == 0:
            required.add(token.rstrip(",]"))
        bracket_depth -= token.count("]")
    return required


def _split_help_columns(line: str) -> tuple[str, str] | None:
    """Split one help-text line into a syntax column and a description column."""
    stripped = line.strip()
    if not stripped:
        return None
    parts = re.split(r"\s{2,}", stripped, maxsplit=1)
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[1]


def _parse_option_parameter(
    syntax: str,
    description: str,
    *,
    required_options: set[str],
) -> _CliParameter | None:
    """Parse one option-style help line into a generated parameter."""
    if "--help" in syntax or syntax.startswith("-h"):
        return None
    matches: list[tuple[str, str | None]] = []
    for raw_part in syntax.split(","):
        part = raw_part.strip()
        match = re.match(r"^(--?[A-Za-z0-9][A-Za-z0-9_-]*)(?:[ =](.+))?$", part)
        if match is None:
            continue
        matches.append((match.group(1), match.group(2)))
    if not matches:
        return None
    preferred_option = next(
        (option for option, _ in matches if option.startswith("--")),
        matches[0][0],
    )
    value_hint = next((value for _, value in matches if value), None)
    takes_value = value_hint is not None
    inverted_boolean = preferred_option.startswith("--no-") and not takes_value
    name = preferred_option[5:] if inverted_boolean else preferred_option.lstrip("-")
    name = _sanitize_name(name.replace("-", "_"))
    if not name:
        return None
    required = preferred_option in required_options or "required" in description.lower()
    if not takes_value:
        return _CliParameter(
            name=name,
            positional=False,
            syntax=syntax,
            emitted_option=preferred_option,
            annotation_source="bool",
            required=False,
            default_source="True" if inverted_boolean else "False",
            description=description or f"Toggle {preferred_option}.",
            takes_value=False,
            inverted_boolean=inverted_boolean,
        )

    default_value = _parse_default_from_description(description)
    annotation_source = _infer_cli_value_annotation(value_hint, default_value)
    default_source: str | None
    if required and default_value is _DEFAULT_MISSING:
        default_source = None
    else:
        default_source = "None" if default_value is _DEFAULT_MISSING else repr(default_value)
        annotation_source = f"{annotation_source} | None"
    return _CliParameter(
        name=name,
        positional=False,
        syntax=syntax,
        emitted_option=preferred_option,
        annotation_source=annotation_source,
        required=required,
        default_source=default_source,
        description=description or f"Forwarded as {preferred_option}.",
        takes_value=True,
    )


def _parse_positional_parameter(
    syntax: str,
    description: str,
) -> _CliParameter | None:
    """Parse one positional-argument help line into a generated parameter."""
    token = syntax.split()[0]
    name = _sanitize_name(token.replace("-", "_"))
    if not name:
        return None
    return _CliParameter(
        name=name,
        positional=True,
        syntax=syntax,
        emitted_option=None,
        annotation_source="str",
        required=True,
        default_source=None,
        description=description or f"Forwarded as positional argument {token}.",
        takes_value=True,
    )


def _parse_default_from_description(description: str) -> object:
    """Extract a simple default value from a CLI help description when present."""
    match = re.search(
        r"(?i)\bdefault(?:s)?(?:\s+to)?\s*[:=]?\s*['\"]?([^)\];,]+)['\"]?",
        description,
    )
    if match is None:
        return _DEFAULT_MISSING
    raw_value = match.group(1).strip()
    lowered = raw_value.lower()
    if lowered in {"none", "null"}:
        return None
    bool_value = _parse_bool_token(lowered)
    if bool_value is not None:
        return bool_value
    number_value = _parse_number_token(raw_value)
    if number_value is not None:
        return number_value
    return raw_value


def _parse_bool_token(value: str) -> bool | None:
    """Parse a textual boolean token when it is unambiguous."""
    if value in {"true", "yes", "on", "enabled"}:
        return True
    if value in {"false", "no", "off", "disabled"}:
        return False
    return None


def _parse_number_token(value: str) -> int | float | None:
    """Parse a textual number token when it is unambiguous."""
    if re.fullmatch(r"[+-]?[0-9]+", value):
        return int(value)
    if re.fullmatch(r"[+-]?(?:[0-9]*\.[0-9]+|[0-9]+\.[0-9]*)(?:[eE][+-]?[0-9]+)?", value):
        return float(value)
    return None


def _infer_cli_value_annotation(value_hint: str | None, default_value: object) -> str:
    """Infer a useful Python annotation source for one CLI option value."""
    if isinstance(default_value, bool):
        return "bool"
    if isinstance(default_value, int) and not isinstance(default_value, bool):
        return "int"
    if isinstance(default_value, float):
        return "float"
    normalized_hint = (value_hint or "").strip().lower()
    if normalized_hint in {"int", "integer", "count", "counts", "num", "number"}:
        return "int"
    if normalized_hint in {"float", "double", "ratio", "scale"}:
        return "float"
    return "str"


def _render_package_facade(
    package_name: str,
    *,
    function_specs: tuple[_FunctionSpec, ...],
    class_specs: tuple[_ClassSpec, ...],
) -> str:
    """Render the generated Python facade module for one package."""
    parts = [
        f'"""Generated by ``mcpcraft scaffold-package`` for ``{package_name}``.',
        "",
        "This module is deterministic scaffolding. It is meant to be inspected,",
        "tested, and then wrapped through normal ``mcpcraft`` discovery.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "import importlib",
        "import threading",
        "from pathlib import Path",
        "from typing import Any",
        "from uuid import uuid4",
        "",
        "_SESSIONS: dict[str, object] = {}",
        "_SESSION_TYPES: dict[str, str] = {}",
        "_SESSION_LOCK = threading.Lock()",
        "",
        "",
        "def _resolve_symbol(module_name: str, qualname: str) -> Any:",
        '    """Resolve one dotted symbol path lazily at call time."""',
        "    module = importlib.import_module(module_name)",
        "    value: Any = module",
        "    for part in qualname.split('.'):",
        "        value = getattr(value, part)",
        "    return value",
        "",
        "",
        "def _register_session(instance: object, class_path: str) -> dict[str, str]:",
        '    """Register one live Python object and return a session record."""',
        "    session_id = uuid4().hex",
        "    with _SESSION_LOCK:",
        "        _SESSIONS[session_id] = instance",
        "        _SESSION_TYPES[session_id] = class_path",
        '    return {"session_id": session_id, "class_path": class_path}',
        "",
        "",
        "def _require_session(session_id: str, class_path: str) -> object:",
        '    """Return one registered session object after validating its type."""',
        "    with _SESSION_LOCK:",
        "        if session_id not in _SESSIONS:",
        "            raise KeyError(f'Unknown session_id: {session_id}')",
        "        if _SESSION_TYPES.get(session_id) != class_path:",
        "            raise TypeError(",
        "                f'Session {session_id} belongs to '",
        "                f'{_SESSION_TYPES.get(session_id)!r}, not {class_path!r}.'",
        "            )",
        "        return _SESSIONS[session_id]",
        "",
        "",
        "def _close_session(session_id: str, class_path: str) -> dict[str, object]:",
        '    """Remove one registered session and call ``close()`` when available."""',
        "    with _SESSION_LOCK:",
        "        instance = _SESSIONS.pop(session_id, None)",
        "        registered_type = _SESSION_TYPES.pop(session_id, None)",
        "    if instance is None:",
        "        raise KeyError(f'Unknown session_id: {session_id}')",
        "    if registered_type != class_path:",
        "        raise TypeError(",
        "            f'Session {session_id} belongs to {registered_type!r}, '",
        "            f'not {class_path!r}.'",
        "        )",
        "    close_method = getattr(instance, 'close', None)",
        "    if callable(close_method):",
        "        close_method()",
        '    return {"success": True, "session_id": session_id, "class_path": class_path}',
        "",
    ]
    for spec in function_specs:
        parts.extend(_render_function_wrapper(spec))
    for class_spec in class_specs:
        parts.extend(_render_class_wrappers(class_spec))
    return "\n".join(parts).rstrip() + "\n"


def _render_function_wrapper(spec: _FunctionSpec) -> list[str]:
    """Render one generated function wrapper."""
    if spec.style == "named":
        parameter_source = _parameter_source(spec.parameters)
        call_source = ", ".join(
            f"{parameter.name}={parameter.name}" for parameter in spec.parameters
        )
        signature = parameter_source or ""
        invocation = f"({call_source})" if call_source else "()"
        return [
            f"def {spec.name}({signature}) -> Any:",
            *(_docstring_lines(_function_docstring(spec, payload_style=False), indent="    ")),
            f"    target = _resolve_symbol({spec.module_name!r}, {spec.qualname!r})",
            f"    return target{invocation}",
            "",
            "",
        ]
    return [
        (
            f"def {spec.name}("
            "args: list[Any] | None = None, "
            "kwargs: dict[str, Any] | None = None"
            ") -> Any:"
        ),
        *(_docstring_lines(_function_docstring(spec, payload_style=True), indent="    ")),
        f"    target = _resolve_symbol({spec.module_name!r}, {spec.qualname!r})",
        "    return target(*(args or []), **(kwargs or {}))",
        "",
        "",
    ]


def _render_class_wrappers(spec: _ClassSpec) -> list[str]:
    """Render all wrappers for one generated class session facade."""
    lines: list[str] = []
    class_path = spec.source
    if spec.constructor_style == "named":
        parameter_source = _parameter_source(spec.constructor_parameters)
        call_source = ", ".join(
            f"{parameter.name}={parameter.name}" for parameter in spec.constructor_parameters
        )
        invocation = f"({call_source})" if call_source else "()"
        lines.extend(
            [
                f"def {spec.create_name}({parameter_source}) -> dict[str, str]:",
                *(
                    _docstring_lines(
                        _class_create_docstring(spec, payload_style=False),
                        indent="    ",
                    )
                ),
                f"    cls = _resolve_symbol({spec.module_name!r}, {spec.qualname!r})",
                f"    instance = cls{invocation}",
                f"    return _register_session(instance, {class_path!r})",
                "",
                "",
            ]
        )
    else:
        lines.extend(
            [
                f"def {spec.create_name}(",
                "    args: list[Any] | None = None,",
                "    kwargs: dict[str, Any] | None = None,",
                ") -> dict[str, str]:",
                *(
                    _docstring_lines(
                        _class_create_docstring(spec, payload_style=True),
                        indent="    ",
                    )
                ),
                f"    cls = _resolve_symbol({spec.module_name!r}, {spec.qualname!r})",
                "    instance = cls(*(args or []), **(kwargs or {}))",
                f"    return _register_session(instance, {class_path!r})",
                "",
                "",
            ]
        )
    for method_spec in spec.method_specs:
        if method_spec.style == "named":
            parameter_source = _parameter_source(method_spec.parameters)
            signature = (
                f"session_id: str, {parameter_source}" if parameter_source else "session_id: str"
            )
            call_source = ", ".join(
                f"{parameter.name}={parameter.name}" for parameter in method_spec.parameters
            )
            invocation = f"({call_source})" if call_source else "()"
            lines.extend(
                [
                    f"def {method_spec.name}({signature}) -> Any:",
                    *(
                        _docstring_lines(
                            _class_method_docstring(spec, method_spec, payload_style=False),
                            indent="    ",
                        )
                    ),
                    f"    instance = _require_session(session_id, {class_path!r})",
                    (
                        "    method = getattr("
                        f"instance, {method_spec.qualname.rsplit('.', 1)[-1]!r})"
                    ),
                    f"    return method{invocation}",
                    "",
                    "",
                ]
            )
            continue
        lines.extend(
            [
                f"def {method_spec.name}(",
                "    session_id: str,",
                "    args: list[Any] | None = None,",
                "    kwargs: dict[str, Any] | None = None,",
                ") -> Any:",
                *(
                    _docstring_lines(
                        _class_method_docstring(spec, method_spec, payload_style=True),
                        indent="    ",
                    )
                ),
                f"    instance = _require_session(session_id, {class_path!r})",
                (f"    method = getattr(instance, {method_spec.qualname.rsplit('.', 1)[-1]!r})"),
                "    return method(*(args or []), **(kwargs or {}))",
                "",
                "",
            ]
        )
    lines.extend(
        [
            f"def {spec.close_name}(session_id: str) -> dict[str, object]:",
            *(_docstring_lines(_class_close_docstring(spec), indent="    ")),
            f"    return _close_session(session_id, {class_path!r})",
            "",
            "",
        ]
    )
    return lines


def _parameter_source(parameters: tuple[inspect.Parameter, ...]) -> str:
    """Render a Python parameter list with stable source annotations."""
    parts: list[str] = []
    inserted_keyword_marker = False
    for parameter in parameters:
        if parameter.kind is inspect.Parameter.KEYWORD_ONLY and not inserted_keyword_marker:
            parts.append("*")
            inserted_keyword_marker = True
        annotation_source = _annotation_source(parameter.annotation)
        default_source = ""
        if parameter.default is not inspect.Signature.empty:
            rendered_default = _default_source(parameter.default)
            if rendered_default is None:
                raise ValueError(f"Unsupported default for named wrapper: {parameter.default!r}")
            default_source = f" = {rendered_default}"
        parts.append(f"{parameter.name}: {annotation_source}{default_source}")
    return ", ".join(parts)


def _annotation_source(annotation: object) -> str:
    """Render a stable Python annotation source for generated wrappers."""
    if annotation in (inspect.Signature.empty, Any, object):
        return "Any"
    if annotation is type(None):
        return "None"
    if isinstance(annotation, str) and annotation.strip():
        return _annotation_source_from_string(annotation)
    if annotation in (str, int, float, bool, bytes) and isinstance(annotation, type):
        return str(annotation.__name__)
    if annotation is Path:
        return "Path"
    if _is_pathlike_annotation(annotation):
        return "Path"
    origin = get_origin(annotation)
    if origin is Annotated:
        arguments = get_args(annotation)
        if not arguments:
            return "Any"
        return _annotation_source(arguments[0])
    if origin in (list, tuple, set, frozenset, os.PathLike):
        if origin is os.PathLike:
            return "Path"
        arguments = get_args(annotation)
        item_source = _annotation_source(arguments[0]) if arguments else "Any"
        return f"list[{item_source}]"
    if origin is dict or _is_mapping_origin(origin):
        arguments = get_args(annotation)
        if len(arguments) != 2:
            return "dict[str, Any]"
        key_source = _annotation_source(arguments[0])
        value_source = _annotation_source(arguments[1])
        if key_source != "str":
            return "dict[str, Any]"
        return f"dict[str, {value_source}]"
    if _is_sequence_origin(origin):
        arguments = get_args(annotation)
        item_source = _annotation_source(arguments[0]) if arguments else "Any"
        return f"list[{item_source}]"
    if origin in (types.UnionType, Union):
        arguments = get_args(annotation)
        if arguments:
            normalized = [_annotation_source(argument) for argument in arguments]
            return " | ".join(normalized)
    if _is_numpy_array_annotation(annotation):
        return "list[float]"
    return "Any"


def _docstring_lines(text: str, *, indent: str) -> list[str]:
    """Render one valid docstring literal at a specific indentation level."""
    return [f"{indent}{json.dumps(text)}"]


def _param_field(name: str, description: str) -> str:
    """Render one Sphinx-style parameter field line."""
    return f":param {name}: {description}"


def _function_docstring(spec: _FunctionSpec, *, payload_style: bool) -> str:
    """Build the generated docstring for one function wrapper."""
    lines = [
        spec.summary,
        "",
        f"Generated wrapper for ``{spec.source}``.",
        f"Original signature: ``{spec.signature_text}``.",
    ]
    if payload_style:
        lines.extend(
            [
                _param_field(
                    "args",
                    "Optional positional arguments forwarded to the original callable.",
                ),
                _param_field(
                    "kwargs",
                    "Optional keyword arguments forwarded to the original callable.",
                ),
            ]
        )
    else:
        for parameter in spec.parameters:
            description = spec.param_descriptions.get(
                parameter.name,
                f"Forwarded to ``{spec.source}``.",
            )
            lines.append(_param_field(parameter.name, description))
    lines.extend(
        [
            "",
            f":returns: Original return value from ``{spec.source}``.",
        ]
    )
    return "\n".join(lines)


def _class_create_docstring(spec: _ClassSpec, *, payload_style: bool) -> str:
    """Build the generated docstring for one class session creator."""
    lines = [
        spec.summary,
        "",
        f"Generated session creator for ``{spec.source}``.",
        f"Original constructor signature: ``{spec.constructor_signature_text}``.",
    ]
    if payload_style:
        lines.extend(
            [
                _param_field("args", "Optional positional constructor arguments."),
                _param_field("kwargs", "Optional keyword constructor arguments."),
            ]
        )
    else:
        for parameter in spec.constructor_parameters:
            description = spec.constructor_param_descriptions.get(
                parameter.name,
                f"Forwarded to ``{spec.source}``.",
            )
            lines.append(_param_field(parameter.name, description))
    lines.extend(
        [
            "",
            ":returns: Session metadata including the generated ``session_id``.",
        ]
    )
    return "\n".join(lines)


def _class_method_docstring(
    class_spec: _ClassSpec,
    method_spec: _FunctionSpec,
    *,
    payload_style: bool,
) -> str:
    """Build the generated docstring for one session-bound class method wrapper."""
    lines = [
        method_spec.summary,
        "",
        f"Generated session method wrapper for ``{method_spec.source}``.",
        f"Original signature: ``{method_spec.signature_text}``.",
        _param_field(
            "session_id",
            "Session identifier returned by the class session creator.",
        ),
    ]
    if payload_style:
        lines.extend(
            [
                _param_field("args", "Optional positional method arguments."),
                _param_field("kwargs", "Optional keyword method arguments."),
            ]
        )
    else:
        for parameter in method_spec.parameters:
            description = method_spec.param_descriptions.get(
                parameter.name,
                f"Forwarded to ``{method_spec.source}``.",
            )
            lines.append(_param_field(parameter.name, description))
    lines.extend(
        [
            "",
            f":returns: Original return value from ``{method_spec.source}``.",
        ]
    )
    return "\n".join(lines)


def _class_close_docstring(spec: _ClassSpec) -> str:
    """Build the generated docstring for one session closer."""
    return "\n".join(
        [
            f"Close a managed session for ``{spec.source}``.",
            "",
            _param_field(
                "session_id",
                "Session identifier returned by the class session creator.",
            ),
            "",
            ":returns: Session-close metadata.",
        ]
    )


def _render_command_facade(
    *,
    command: tuple[str, ...],
    function_name: str,
    help_text: str | None,
    parameters: tuple[_CliParameter, ...],
) -> str:
    """Render the generated Python facade module for one CLI command."""
    help_section = ""
    if help_text:
        help_lines = ["", "Command help captured at scaffold time:", ""] + [
            f"    {line}" if line else "" for line in help_text.strip().splitlines()
        ]
        help_section = "\n".join(help_lines)
    command_json = json.dumps(list(command))
    if parameters:
        return _render_named_command_facade(
            command=command,
            command_json=command_json,
            function_name=function_name,
            help_section=help_section,
            parameters=parameters,
        )
    return "\n".join(
        [
            f'"""Generated by ``mcpcraft scaffold-command`` for ``{" ".join(command)}``.',
            "",
            "This module is deterministic scaffolding around a CLI entry point.",
            '"""',
            "",
            "from __future__ import annotations",
            "",
            "import os",
            "import subprocess",
            "import sys",
            "from typing import Any",
            "",
            f"_BASE_COMMAND = tuple({command_json})",
            "_PYTHON_BIN_DIR = os.path.dirname(sys.executable)",
            "",
            "",
            f"def {function_name}(",
            "    argv: list[str] | None = None,",
            "    stdin_text: str | None = None,",
            "    cwd: str | None = None,",
            "    env: dict[str, str] | None = None,",
            ") -> dict[str, Any]:",
            *(
                _docstring_lines(
                    "\n".join(
                        [
                            "Run the scaffolded CLI command.",
                            "",
                            f"Generated wrapper for ``{' '.join(command)}``.{help_section}",
                            "",
                            _param_field(
                                "argv",
                                (
                                    "Additional command-line arguments appended after the base "
                                    "command."
                                ),
                            ),
                            _param_field("stdin_text", "Optional standard input text."),
                            _param_field("cwd", "Optional working directory."),
                            _param_field("env", "Optional environment variable overrides."),
                            "",
                            ":returns: Structured subprocess execution details.",
                        ]
                    ),
                    indent="    ",
                )
            ),
            "    final_argv = [*_BASE_COMMAND, *(argv or [])]",
            "    completed = subprocess.run(",
            "        final_argv,",
            "        input=stdin_text,",
            "        capture_output=True,",
            "        text=True,",
            "        cwd=cwd,",
            "        env=_command_env(env),",
            "        check=False,",
            "    )",
            "    return {",
            '        "argv": final_argv,',
            '        "cwd": cwd,',
            '        "stdout": completed.stdout,',
            '        "stderr": completed.stderr,',
            '        "exit_code": completed.returncode,',
            "    }",
            "",
            "",
            "def _command_env(env: dict[str, str] | None) -> dict[str, str]:",
            (
                '    """Return subprocess environment overrides with the current '
                'interpreter bin first."""'
            ),
            "    merged = {**os.environ, **(env or {})}",
            "    merged_path = merged.get('PATH', '')",
            "    if merged_path:",
            "        merged['PATH'] = os.pathsep.join([_PYTHON_BIN_DIR, merged_path])",
            "    else:",
            "        merged['PATH'] = _PYTHON_BIN_DIR",
            "    return merged",
            "",
        ]
    )


def _render_named_command_facade(
    *,
    command: tuple[str, ...],
    command_json: str,
    function_name: str,
    help_section: str,
    parameters: tuple[_CliParameter, ...],
) -> str:
    """Render a CLI facade that exposes named arguments inferred from help text."""
    signature_lines = _command_signature_lines(parameters)
    docstring_lines = _docstring_lines(
        _named_command_docstring(
            command=command,
            parameters=parameters,
            help_section=help_section,
        ),
        indent="    ",
    )
    invocation_lines = _command_invocation_lines(parameters)
    return "\n".join(
        [
            f'"""Generated by ``mcpcraft scaffold-command`` for ``{" ".join(command)}``.',
            "",
            "This module is deterministic scaffolding around a CLI entry point.",
            '"""',
            "",
            "from __future__ import annotations",
            "",
            "import os",
            "import subprocess",
            "import sys",
            "from typing import Any",
            "",
            f"_BASE_COMMAND = tuple({command_json})",
            "_PYTHON_BIN_DIR = os.path.dirname(sys.executable)",
            "",
            "",
            "def _command_env(env: dict[str, str] | None) -> dict[str, str]:",
            (
                '    """Return subprocess environment overrides with the current '
                'interpreter bin first."""'
            ),
            "    merged = {**os.environ, **(env or {})}",
            "    merged_path = merged.get('PATH', '')",
            "    if merged_path:",
            "        merged['PATH'] = os.pathsep.join([_PYTHON_BIN_DIR, merged_path])",
            "    else:",
            "        merged['PATH'] = _PYTHON_BIN_DIR",
            "    return merged",
            "",
            "",
            f"def {function_name}(",
            *signature_lines,
            ") -> dict[str, Any]:",
            *docstring_lines,
            "    final_argv = list(_BASE_COMMAND)",
            *invocation_lines,
            "    completed = subprocess.run(",
            "        final_argv,",
            "        input=stdin_text,",
            "        capture_output=True,",
            "        text=True,",
            "        cwd=cwd,",
            "        env=_command_env(env),",
            "        check=False,",
            "    )",
            "    return {",
            '        "argv": final_argv,',
            '        "cwd": cwd,',
            '        "stdout": completed.stdout,',
            '        "stderr": completed.stderr,',
            '        "exit_code": completed.returncode,',
            "    }",
            "",
        ]
    )


def _command_signature_lines(parameters: tuple[_CliParameter, ...]) -> list[str]:
    """Render the signature lines for a named CLI facade."""
    lines = [f"    {_command_parameter_source(parameter)}," for parameter in parameters]
    lines.extend(
        [
            "    extra_argv: list[str] | None = None,",
            "    stdin_text: str | None = None,",
            "    cwd: str | None = None,",
            "    env: dict[str, str] | None = None,",
        ]
    )
    return lines


def _command_parameter_source(parameter: _CliParameter) -> str:
    """Render one CLI parameter into Python signature source."""
    if parameter.required and parameter.default_source is None:
        return f"{parameter.name}: {parameter.annotation_source}"
    default_source = parameter.default_source or "None"
    return f"{parameter.name}: {parameter.annotation_source} = {default_source}"


def _named_command_docstring(
    *,
    command: tuple[str, ...],
    parameters: tuple[_CliParameter, ...],
    help_section: str,
) -> str:
    """Build the generated docstring for a named CLI wrapper."""
    lines = [
        "Run the scaffolded CLI command.",
        "",
        f"Generated wrapper for ``{' '.join(command)}``.{help_section}",
    ]
    for parameter in parameters:
        description = parameter.description or "Forwarded to the underlying CLI."
        lines.append(
            _param_field(
                parameter.name,
                f"{description} Mapped from ``{parameter.syntax}``.",
            )
        )
    lines.extend(
        [
            _param_field("extra_argv", "Extra arguments appended after the named interface."),
            _param_field("stdin_text", "Optional standard input text."),
            _param_field("cwd", "Optional working directory."),
            _param_field("env", "Optional environment variable overrides."),
            "",
            ":returns: Structured subprocess execution details.",
        ]
    )
    return "\n".join(lines)


def _command_invocation_lines(parameters: tuple[_CliParameter, ...]) -> list[str]:
    """Render the argument-assembly lines for a named CLI wrapper."""
    lines: list[str] = []
    for parameter in parameters:
        if parameter.positional:
            lines.append(f"    final_argv.append(str({parameter.name}))")
            continue
        if not parameter.takes_value:
            if parameter.inverted_boolean:
                lines.append(f"    if not {parameter.name}:")
            else:
                lines.append(f"    if {parameter.name}:")
            lines.append(f"        final_argv.append({parameter.emitted_option!r})")
            continue
        lines.append(f"    if {parameter.name} is not None:")
        lines.append(
            f"        final_argv.extend([{parameter.emitted_option!r}, str({parameter.name})])"
        )
    lines.append("    final_argv.extend(extra_argv or [])")
    return lines


def _capture_help_text(
    command: tuple[str, ...],
    *,
    timeout_seconds: float,
    help_probe_args: tuple[str, ...] = ("--help",),
) -> str | None:
    """Capture ``--help`` output for one CLI command when available."""
    import subprocess

    try:
        command_env = dict(os.environ)
        python_bin_dir = os.path.dirname(sys.executable)
        existing_path = command_env.get("PATH", "")
        command_env["PATH"] = (
            os.pathsep.join([python_bin_dir, existing_path]) if existing_path else python_bin_dir
        )
        completed = subprocess.run(
            [*command, *help_probe_args],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
            env=command_env,
        )
    except Exception:
        return None
    output = completed.stdout.strip() or completed.stderr.strip()
    return output or None


def _compile_patterns(patterns: tuple[str, ...]) -> tuple[re.Pattern[str], ...]:
    """Compile regex filters for scaffold include and exclude lists."""
    return tuple(re.compile(pattern) for pattern in patterns)


def _matches_patterns(
    value: str,
    includes: tuple[re.Pattern[str], ...],
    excludes: tuple[re.Pattern[str], ...],
) -> bool:
    """Return whether one value survives include and exclude regex filters."""
    if includes and not any(pattern.search(value) for pattern in includes):
        return False
    return not any(pattern.search(value) for pattern in excludes)


def _within_namespace(module_name: str, namespace: str) -> bool:
    """Return whether one module path stays inside the target namespace."""
    return module_name == namespace or module_name.startswith(f"{namespace}.")


def _value_source(value: object) -> str | None:
    """Render one default value into valid Python source when feasible."""
    if value is None or isinstance(value, (str, int, float, bool, bytes)):
        return repr(value)
    if isinstance(value, Path):
        return f"Path({value.as_posix()!r})"
    if isinstance(value, Enum):
        return (
            "_resolve_symbol("
            f"{value.__class__.__module__!r}, "
            f"{value.__class__.__qualname__ + '.' + value.name!r}"
            ")"
        )
    if isinstance(value, list):
        rendered = [_value_source(item) for item in value]
        if any(item is None for item in rendered):
            return None
        return f"[{', '.join(item for item in rendered if item is not None)}]"
    if isinstance(value, tuple):
        rendered = [_value_source(item) for item in value]
        if any(item is None for item in rendered):
            return None
        suffix = "," if len(rendered) == 1 else ""
        return f"({', '.join(item for item in rendered if item is not None)}{suffix})"
    if isinstance(value, dict):
        rendered_items: list[str] = []
        for key, item in value.items():
            key_source = _value_source(key)
            item_source = _value_source(item)
            if key_source is None or item_source is None:
                return None
            rendered_items.append(f"{key_source}: {item_source}")
        return "{" + ", ".join(rendered_items) + "}"
    if inspect.isclass(value) or inspect.isfunction(value):
        module_name = getattr(value, "__module__", None)
        qualname = getattr(value, "__qualname__", None)
        if isinstance(module_name, str) and isinstance(qualname, str):
            return f"_resolve_symbol({module_name!r}, {qualname!r})"
    return None


def _annotation_source_from_string(annotation: str) -> str:
    """Normalize a string annotation into a safe generated-source annotation."""
    normalized = (
        annotation.strip()
        .replace("typing.", "")
        .replace("collections.abc.", "")
        .replace("NoneType", "None")
    )
    safe_annotations = {
        "str",
        "int",
        "float",
        "bool",
        "bytes",
        "Path",
        "list",
        "tuple",
        "dict",
        "Sequence",
        "Mapping",
        "Optional",
        "Union",
        "Literal",
        "Annotated",
        "Any",
        "None",
    }
    if "[" in normalized or "|" in normalized or normalized in safe_annotations:
        candidate = normalized
    elif normalized.endswith(".PathLike") or normalized == "PathLike":
        candidate = "Path"
    elif (
        normalized.endswith(".ndarray")
        or normalized.endswith(".NDArray")
        or normalized
        in {
            "ndarray",
            "NDArray",
        }
    ):
        candidate = "list[float]"
    else:
        return "Any"
    candidate = candidate.replace("List[", "list[")
    candidate = candidate.replace("Dict[", "dict[")
    candidate = candidate.replace("Tuple[", "tuple[")
    candidate = candidate.replace("Set[", "list[")
    candidate = candidate.replace("FrozenSet[", "list[")
    candidate = candidate.replace("Sequence[", "list[").replace("Mapping[", "dict[")
    candidate = candidate.replace("PathLike", "Path")
    if candidate.startswith("Optional[") and candidate.endswith("]"):
        inner = candidate[len("Optional[") : -1]
        return f"{_annotation_source_from_string(inner)} | None"
    if candidate.startswith("Union[") and candidate.endswith("]"):
        inner = candidate[len("Union[") : -1]
        members = [_annotation_source_from_string(part) for part in _split_top_level_commas(inner)]
        return " | ".join(members) if members else "Any"
    if candidate.startswith("Annotated[") and candidate.endswith("]"):
        inner = candidate[len("Annotated[") : -1]
        parts = _split_top_level_commas(inner)
        return _annotation_source_from_string(parts[0]) if parts else "Any"
    if candidate.startswith("list[") and candidate.endswith("]"):
        inner = candidate[len("list[") : -1]
        return f"list[{_annotation_source_from_string(inner)}]"
    if candidate.startswith("tuple[") and candidate.endswith("]"):
        inner = candidate[len("tuple[") : -1]
        parts = _split_top_level_commas(inner)
        if not parts:
            return "list[Any]"
        return f"list[{_annotation_source_from_string(parts[0])}]"
    if candidate.startswith("dict[") and candidate.endswith("]"):
        inner = candidate[len("dict[") : -1]
        parts = _split_top_level_commas(inner)
        if len(parts) != 2:
            return "dict[str, Any]"
        key_source = _annotation_source_from_string(parts[0])
        value_source = _annotation_source_from_string(parts[1])
        if key_source != "str":
            return "dict[str, Any]"
        return f"dict[str, {value_source}]"
    return candidate


def _is_pathlike_annotation(annotation: object) -> bool:
    """Return whether one runtime annotation represents a path-like value."""
    if annotation is os.PathLike:
        return True
    return inspect.isclass(annotation) and issubclass(annotation, os.PathLike)


def _is_sequence_origin(origin: object) -> bool:
    """Return whether one typing origin should map to a JSON array."""
    return origin in {list, tuple, abc.Sequence, abc.MutableSequence}


def _is_mapping_origin(origin: object) -> bool:
    """Return whether one typing origin should map to a JSON object mapping."""
    return origin in {abc.Mapping, abc.MutableMapping}


def _is_numpy_array_annotation(annotation: object) -> bool:
    """Return whether one runtime annotation represents a NumPy-style array."""
    module_name = getattr(annotation, "__module__", "")
    qualname = getattr(annotation, "__qualname__", getattr(annotation, "__name__", ""))
    origin = get_origin(annotation)
    if origin is not None:
        module_name = getattr(origin, "__module__", module_name)
        qualname = getattr(origin, "__qualname__", getattr(origin, "__name__", qualname))
    return module_name.startswith("numpy") and qualname in {"ndarray", "NDArray"}


def _split_top_level_commas(value: str) -> list[str]:
    """Split a generic type argument list on commas outside nested brackets."""
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    for character in value:
        if character == "," and depth == 0:
            part = "".join(current).strip()
            if part:
                parts.append(part)
            current = []
            continue
        if character == "[":
            depth += 1
        elif character == "]" and depth > 0:
            depth -= 1
        current.append(character)
    trailing = "".join(current).strip()
    if trailing:
        parts.append(trailing)
    return parts

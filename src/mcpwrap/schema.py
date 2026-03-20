"""Schema generation, validation, and coercion helpers."""

from __future__ import annotations

import base64
import collections.abc
import dataclasses
import inspect
import json
import os
import types
from enum import Enum
from pathlib import Path
from typing import (
    Annotated,
    Any,
    Literal,
    Union,
    cast,
    get_args,
    get_origin,
    get_type_hints,
    is_typeddict,
)


class SchemaGenerationError(ValueError):
    """Raised when a Python type cannot be mapped to supported JSON Schema."""


class SchemaValidationError(ValueError):
    """Raised when input data fails deterministic schema validation."""


def schema_from_annotation(annotation: Any) -> dict[str, Any]:
    """Build JSON Schema for a supported Python type annotation.

    :param annotation: Python annotation object.
    :returns: JSON Schema represented as a dictionary.
    :raises SchemaGenerationError: Raised when the annotation is unsupported.
    """
    if annotation in (Any, object):
        return {}
    if annotation is inspect.Signature.empty:
        raise SchemaGenerationError("Missing type annotation.")
    if annotation is str:
        return {"type": "string"}
    if annotation is int:
        return {"type": "integer"}
    if annotation is float:
        return {"type": "number"}
    if annotation is bool:
        return {"type": "boolean"}
    if annotation is bytes:
        return {
            "type": "string",
            "contentEncoding": "base64",
            "x-mcpwrap-kind": "bytes",
        }
    if annotation is Path:
        return {
            "type": "string",
            "format": "path",
            "x-mcpwrap-kind": "path",
            "x-mcpwrap-path-kind": "auto",
        }
    if _is_pathlike_annotation(annotation):
        return {
            "type": "string",
            "format": "path",
            "x-mcpwrap-kind": "path",
            "x-mcpwrap-path-kind": "auto",
        }
    if annotation is type(None):
        return {"type": "null"}
    if _is_numpy_array_annotation(annotation):
        return {"type": "array", "items": {"type": "number"}}
    origin = get_origin(annotation)
    if origin is os.PathLike:
        return {
            "type": "string",
            "format": "path",
            "x-mcpwrap-kind": "path",
            "x-mcpwrap-path-kind": "auto",
        }
    if origin is Annotated:
        args = get_args(annotation)
        return _apply_annotated_metadata(schema_from_annotation(args[0]), args[1:])
    if origin in (list, tuple, set, frozenset) or _is_sequence_origin(origin):
        args = get_args(annotation)
        item_annotation = args[0] if args else Any
        schema: dict[str, Any] = {"type": "array", "items": schema_from_annotation(item_annotation)}
        if origin in (set, frozenset):
            schema["uniqueItems"] = True
        return schema
    if origin is dict or _is_mapping_origin(origin):
        args = get_args(annotation)
        key_type, value_type = (args[0], args[1]) if len(args) == 2 else (str, Any)
        if key_type is not str:
            raise SchemaGenerationError("Only dict[str, T] is supported.")
        return {
            "type": "object",
            "additionalProperties": schema_from_annotation(value_type),
        }
    if origin in (Union, types.UnionType):
        return _schema_from_union(annotation)
    if origin is Literal:
        values = list(get_args(annotation))
        return {"type": _infer_literal_type(values), "enum": values}
    if inspect.isclass(annotation) and issubclass(annotation, Enum):
        values = [member.value for member in annotation]
        return {"type": _infer_literal_type(values), "enum": values}
    if is_typeddict(annotation):
        return _schema_from_typeddict(annotation)
    if inspect.isclass(annotation) and dataclasses.is_dataclass(annotation):
        return _schema_from_dataclass(annotation)
    raise SchemaGenerationError(f"Unsupported annotation: {annotation!r}")


def _apply_annotated_metadata(schema: dict[str, Any], metadata: tuple[Any, ...]) -> dict[str, Any]:
    """Apply ``typing.Annotated`` metadata to a generated schema."""
    updated = dict(schema)
    for item in metadata:
        if isinstance(item, str):
            if updated.get("format") == "path" and item in {"file", "directory", "auto"}:
                updated["x-mcpwrap-path-kind"] = item
            if updated.get("x-mcpwrap-kind") == "bytes" and item == "binary":
                updated["x-mcpwrap-bytes-kind"] = "binary"
            continue
        if (
            isinstance(item, dict)
            and updated.get("format") == "path"
            and item.get("kind") in {"file", "directory", "auto"}
        ):
            updated["x-mcpwrap-path-kind"] = item["kind"]
    return updated


def _schema_from_union(annotation: Any) -> dict[str, Any]:
    """Build JSON Schema for ``Union`` or ``T | None`` annotations."""
    args = get_args(annotation)
    if len(args) == 2 and type(None) in args:
        other = args[0] if args[1] is type(None) else args[1]
        return {"anyOf": [schema_from_annotation(other), {"type": "null"}]}
    return {"anyOf": [schema_from_annotation(item) for item in args]}


def _infer_literal_type(values: list[object]) -> str:
    """Infer the JSON Schema primitive type for enum-like values."""
    if all(isinstance(value, bool) for value in values):
        return "boolean"
    if all(isinstance(value, int) and not isinstance(value, bool) for value in values):
        return "integer"
    if all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in values):
        return "number"
    return "string"


def _schema_from_typeddict(annotation: Any) -> dict[str, Any]:
    """Build JSON Schema for a ``TypedDict``."""
    hints = get_type_hints(annotation, include_extras=True)
    required = list(getattr(annotation, "__required_keys__", hints.keys()))
    return {
        "type": "object",
        "properties": {name: schema_from_annotation(value) for name, value in hints.items()},
        "required": required,
    }


def _schema_from_dataclass(annotation: type[Any]) -> dict[str, Any]:
    """Build JSON Schema for a dataclass type."""
    hints = get_type_hints(annotation, include_extras=True)
    properties: dict[str, Any] = {}
    required: list[str] = []
    for field_info in dataclasses.fields(cast(Any, annotation)):
        properties[field_info.name] = schema_from_annotation(hints[field_info.name])
        if (
            field_info.default is dataclasses.MISSING
            and field_info.default_factory is dataclasses.MISSING
        ):
            required.append(field_info.name)
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def validate_value(value: Any, schema: dict[str, Any], path: str = "$") -> None:
    """Validate a value against the supported JSON Schema subset.

    :param value: Candidate value to validate.
    :param schema: Supported JSON Schema subset.
    :param path: Human-readable location used in error messages.
    :raises SchemaValidationError: Raised when validation fails.
    """
    if not schema:
        return
    if not any(
        key in schema
        for key in ("type", "anyOf", "enum", "properties", "additionalProperties", "items")
    ):
        return
    if "anyOf" in schema:
        errors: list[SchemaValidationError] = []
        for item_schema in schema["anyOf"]:
            try:
                validate_value(value, item_schema, path)
                return
            except SchemaValidationError as error:
                errors.append(error)
        raise SchemaValidationError(f"{path}: value does not match any supported variant.")
    if "enum" in schema and value not in schema["enum"]:
        raise SchemaValidationError(f"{path}: expected one of {schema['enum']!r}.")
    schema_type = schema.get("type")
    if schema_type == "null":
        if value is not None:
            raise SchemaValidationError(f"{path}: expected null.")
        return
    if schema_type == "string":
        if not isinstance(value, str):
            raise SchemaValidationError(f"{path}: expected a string.")
        return
    if schema_type == "boolean":
        if not isinstance(value, bool):
            raise SchemaValidationError(f"{path}: expected a boolean.")
        return
    if schema_type == "integer":
        if not (isinstance(value, int) and not isinstance(value, bool)):
            raise SchemaValidationError(f"{path}: expected an integer.")
        return
    if schema_type == "number":
        if not (isinstance(value, (int, float)) and not isinstance(value, bool)):
            raise SchemaValidationError(f"{path}: expected a number.")
        return
    if schema_type == "array":
        if not isinstance(value, list):
            raise SchemaValidationError(f"{path}: expected an array.")
        item_schema = schema.get("items", {})
        for index, item in enumerate(value):
            validate_value(item, item_schema, f"{path}[{index}]")
        return
    if schema_type == "object":
        if not isinstance(value, dict):
            raise SchemaValidationError(f"{path}: expected an object.")
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        for field_name in required:
            if field_name not in value:
                raise SchemaValidationError(f"{path}: missing required field {field_name!r}.")
        for field_name, field_value in value.items():
            if field_name in properties:
                validate_value(field_value, properties[field_name], f"{path}.{field_name}")
                continue
            additional = schema.get("additionalProperties", True)
            if additional is False:
                raise SchemaValidationError(f"{path}: unexpected field {field_name!r}.")
            if isinstance(additional, dict):
                validate_value(field_value, additional, f"{path}.{field_name}")
        return
    raise SchemaValidationError(f"{path}: unsupported schema type {schema_type!r}.")


def coerce_value(value: Any, annotation: Any) -> Any:
    """Convert a validated JSON value into a Python call argument."""
    if annotation in (inspect.Signature.empty, Any):
        return value
    if value is None:
        return None
    if annotation in (str, int, float, bool):
        return annotation(value)
    if annotation is bytes:
        return base64.b64decode(value.encode("ascii"))
    if annotation is Path:
        return Path(value)
    if _is_pathlike_annotation(annotation):
        return Path(value)
    if _is_numpy_array_annotation(annotation):
        return [float(item) for item in value]
    origin = get_origin(annotation)
    if origin is os.PathLike:
        return Path(value)
    if origin is Annotated:
        return coerce_value(value, get_args(annotation)[0])
    if origin in (Union, types.UnionType):
        for option in get_args(annotation):
            if option is type(None) and value is None:
                return None
            try:
                return coerce_value(value, option)
            except Exception:
                continue
        return value
    if origin in (list, set, frozenset) or _is_sequence_origin(origin):
        args = get_args(annotation)
        item_type = args[0] if args else Any
        items = [coerce_value(item, item_type) for item in value]
        if origin is set:
            return set(items)
        if origin is frozenset:
            return frozenset(items)
        return items
    if origin is tuple:
        item_type = get_args(annotation)[0]
        return tuple(coerce_value(item, item_type) for item in value)
    if origin is dict or _is_mapping_origin(origin):
        args = get_args(annotation)
        value_type = args[1] if len(args) == 2 else Any
        return {key: coerce_value(item, value_type) for key, item in value.items()}
    if inspect.isclass(annotation) and issubclass(annotation, Enum):
        return annotation(value)
    if is_typeddict(annotation):
        hints = get_type_hints(annotation, include_extras=True)
        return {key: coerce_value(item, hints[key]) for key, item in value.items()}
    if inspect.isclass(annotation) and dataclasses.is_dataclass(annotation):
        hints = get_type_hints(annotation, include_extras=True)
        return cast(Any, annotation)(
            **{key: coerce_value(item, hints[key]) for key, item in value.items()}
        )
    return value


def to_json_compatible(value: Any) -> Any:
    """Convert supported Python values into JSON-compatible data."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii")
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, os.PathLike):
        return os.fspath(value)
    if isinstance(value, (set, frozenset)):
        serialized = [to_json_compatible(item) for item in value]
        return sorted(serialized, key=lambda item: json.dumps(item, sort_keys=True))
    if isinstance(value, Enum):
        return value.value
    if dataclasses.is_dataclass(value):
        return {
            field_info.name: to_json_compatible(getattr(value, field_info.name))
            for field_info in dataclasses.fields(value)
        }
    if isinstance(value, dict):
        return {str(key): to_json_compatible(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_json_compatible(item) for item in value]
    raise TypeError(f"Value is not JSON-compatible: {value!r}")


def _is_pathlike_annotation(annotation: Any) -> bool:
    """Return whether one annotation represents a path-like value."""
    if annotation is os.PathLike:
        return True
    return inspect.isclass(annotation) and issubclass(annotation, os.PathLike)


def _is_sequence_origin(origin: Any) -> bool:
    """Return whether one typing origin should behave like a JSON array."""
    return origin in {
        collections.abc.Sequence,
        collections.abc.MutableSequence,
    }


def _is_mapping_origin(origin: Any) -> bool:
    """Return whether one typing origin should behave like a JSON object mapping."""
    return origin in {
        collections.abc.Mapping,
        collections.abc.MutableMapping,
    }


def _is_numpy_array_annotation(annotation: Any) -> bool:
    """Return whether one annotation represents a NumPy-style numeric array."""
    module_name = getattr(annotation, "__module__", "")
    qualname = getattr(annotation, "__qualname__", getattr(annotation, "__name__", ""))
    origin = get_origin(annotation)
    if origin is not None:
        module_name = getattr(origin, "__module__", module_name)
        qualname = getattr(origin, "__qualname__", getattr(origin, "__name__", qualname))
    return module_name.startswith("numpy") and qualname in {"ndarray", "NDArray"}

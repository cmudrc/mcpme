"""Tests for schema generation, validation, and coercion."""

from __future__ import annotations

import base64
import collections.abc
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Annotated, Any, Literal, TypedDict

import pytest

from mcpwrap.schema import (
    SchemaGenerationError,
    SchemaValidationError,
    coerce_value,
    schema_from_annotation,
    to_json_compatible,
    validate_value,
)


class MeshMode(Enum):
    """Simple enum used by schema tests."""

    FINE = "fine"
    COARSE = "coarse"


class Limits(TypedDict):
    """Typed dictionary used by schema tests."""

    max_iterations: int


@dataclass
class SolverConfig:
    """Dataclass used by schema tests."""

    job_name: str
    limits: Limits
    mode: MeshMode


class _FakePathLike(os.PathLike[str]):
    """Simple path-like value for JSON-compatibility tests."""

    def __init__(self, value: str) -> None:
        self.value = value

    def __fspath__(self) -> str:
        return self.value


class _FakeNdArray:
    """Simple fake NumPy array annotation for schema tests."""


_FakeNdArray.__module__ = "numpy"
_FakeNdArray.__qualname__ = "ndarray"


def test_schema_generation_and_validation_cover_supported_types() -> None:
    """Supported annotations should map to deterministic JSON Schema."""

    solver_schema = schema_from_annotation(SolverConfig)
    literal_schema = schema_from_annotation(Literal["mesh", "solve"])
    optional_schema = schema_from_annotation(list[int] | None)
    mapping_schema = schema_from_annotation(dict[str, float])

    assert solver_schema["type"] == "object"
    assert (
        solver_schema["properties"]["limits"]["properties"]["max_iterations"]["type"] == "integer"
    )
    assert literal_schema == {"type": "string", "enum": ["mesh", "solve"]}
    assert optional_schema["anyOf"][0]["type"] == "array"
    assert mapping_schema["additionalProperties"]["type"] == "number"

    validate_value(
        {
            "job_name": "wing_box",
            "limits": {"max_iterations": 10},
            "mode": "fine",
        },
        solver_schema,
    )
    validate_value({"a": 1.2}, mapping_schema)


def test_schema_coercion_and_json_conversion_cover_nested_objects() -> None:
    """Nested structured values should coerce and round-trip cleanly."""

    coerced = coerce_value(
        {
            "job_name": "wing_box",
            "limits": {"max_iterations": 10},
            "mode": "coarse",
        },
        SolverConfig,
    )

    assert isinstance(coerced, SolverConfig)
    assert coerced.mode is MeshMode.COARSE
    assert to_json_compatible(coerced) == {
        "job_name": "wing_box",
        "limits": {"max_iterations": 10},
        "mode": "coarse",
    }


def test_schema_supports_paths_bytes_and_annotated_metadata() -> None:
    """Filesystem and binary annotations should map cleanly into deterministic schemas."""

    file_path_schema = schema_from_annotation(Annotated[Path, "file"])
    bytes_schema = schema_from_annotation(Annotated[bytes, "binary"])

    assert file_path_schema["format"] == "path"
    assert file_path_schema["x-mcpwrap-path-kind"] == "file"
    assert bytes_schema["contentEncoding"] == "base64"
    assert coerce_value("mesh.inp", Path) == Path("mesh.inp")
    assert coerce_value(base64.b64encode(b"abc").decode("ascii"), bytes) == b"abc"
    assert to_json_compatible(b"abc") == base64.b64encode(b"abc").decode("ascii")


def test_schema_supports_pathlike_sequence_mapping_and_numpy_style_inputs() -> None:
    """Extended container-like and path-like annotations should stay deterministic."""

    pathlike_schema = schema_from_annotation(os.PathLike[str])
    sequence_schema = schema_from_annotation(collections.abc.Sequence[int])
    mapping_schema = schema_from_annotation(collections.abc.Mapping[str, float])
    ndarray_schema = schema_from_annotation(_FakeNdArray)
    set_schema = schema_from_annotation(set[str])

    assert pathlike_schema["format"] == "path"
    assert sequence_schema == {"type": "array", "items": {"type": "integer"}}
    assert mapping_schema["additionalProperties"]["type"] == "number"
    assert ndarray_schema == {"type": "array", "items": {"type": "number"}}
    assert set_schema == {"type": "array", "items": {"type": "string"}, "uniqueItems": True}

    assert coerce_value("deck.inp", os.PathLike[str]) == Path("deck.inp")
    assert coerce_value([1, 2, 3], collections.abc.Sequence[int]) == [1, 2, 3]
    assert coerce_value({"alpha": 1.5}, collections.abc.Mapping[str, float]) == {"alpha": 1.5}
    assert coerce_value([1, 2.5], _FakeNdArray) == [1.0, 2.5]
    assert coerce_value(["wing", "tail"], set[str]) == {"wing", "tail"}
    assert to_json_compatible(_FakePathLike("mesh.bdf")) == "mesh.bdf"


def test_schema_supports_any_as_a_permissive_escape_hatch() -> None:
    """``Any`` should remain a deterministic but permissive schema."""

    schema = schema_from_annotation(Any)

    assert schema == {}
    validate_value({"arbitrary": ["payload", 3]}, schema)
    assert coerce_value({"nested": True}, Any) == {"nested": True}


def test_schema_errors_are_explicit_for_unsupported_or_invalid_values() -> None:
    """Unsupported types and invalid values should fail clearly."""

    with pytest.raises(SchemaGenerationError):
        schema_from_annotation(complex)

    with pytest.raises(SchemaValidationError):
        validate_value("oops", {"type": "integer"})

    with pytest.raises(TypeError):
        to_json_compatible(object())

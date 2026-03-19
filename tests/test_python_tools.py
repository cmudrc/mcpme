"""Tests for static Python source parsing helpers."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from mcpme._python_tools import (
    StaticPythonResolver,
    _literal_str_sequence,
    _parameter_defaults,
    find_module_source_path,
    load_module_from_path,
    resolve_qualname,
)
from mcpme.schema import SchemaGenerationError


def test_static_python_resolver_supports_source_types_and_module_reexports(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Source parsing should cover rich types without importing user code."""

    source = tmp_path / "typed_solver.py"
    source.write_text(
        "from dataclasses import dataclass\n"
        "from enum import Enum\n"
        "from pathlib import Path\n"
        "from typing import Annotated, Literal, TypedDict\n\n"
        "class Mode(Enum):\n"
        "    FINE = 'fine'\n\n"
        "class Limits(TypedDict, total=False):\n"
        "    max_iterations: int\n\n"
        "@dataclass\n"
        "class Config:\n"
        "    deck: Annotated[Path, 'file']\n"
        "    limits: Limits\n"
        "    mode: Mode = Mode.FINE\n\n"
        "def run_solver(\n"
        "    config: Config,\n"
        "    payload: bytes,\n"
        "    label: Literal['mesh', 'solve'] = 'mesh',\n"
        ") -> Path:\n"
        '    """Run a static solver.\n\n'
        "    :param config: Structured config.\n"
        "    :param payload: Binary payload.\n"
        "    :param label: Operation label.\n"
        "    :returns: Output deck path.\n"
        '    """\n'
        "    return config.deck\n",
        encoding="utf-8",
    )

    resolver = StaticPythonResolver()
    discovered = resolver.discover_file(source)

    deck_schema = discovered[0].tool.input_schema["properties"]["config"]["properties"]["deck"]
    assert deck_schema["format"] == "path"
    assert (
        discovered[0].tool.input_schema["properties"]["config"]["properties"]["deck"][
            "x-mcpme-path-kind"
        ]
        == "file"
    )
    assert discovered[0].tool.input_schema["properties"]["payload"]["contentEncoding"] == "base64"
    assert discovered[0].tool.input_schema["properties"]["label"]["enum"] == ["mesh", "solve"]
    assert discovered[0].tool.output_schema == {
        "type": "string",
        "format": "path",
        "x-mcpme-kind": "path",
        "x-mcpme-path-kind": "auto",
    }

    package_dir = tmp_path / "solver_pkg"
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text(
        '__all__ = ["solve"]\nfrom .solver import run_solver as solve\n',
        encoding="utf-8",
    )
    (package_dir / "solver.py").write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    exported = resolver.discover_module("solver_pkg")
    assert exported[0].tool.name == "solve"
    assert find_module_source_path("solver_pkg") == (package_dir / "__init__.py").resolve()


def test_static_python_resolver_helper_edges_are_explicit(tmp_path: Path) -> None:
    """Unsupported signatures and helper branches should fail clearly."""

    resolver = StaticPythonResolver()
    unsupported = tmp_path / "unsupported.py"
    unsupported.write_text(
        "from pathlib import Path\n"
        "from typing import Annotated\n\n"
        "def positional(value: str, /) -> str:\n"
        "    return value\n\n"
        "def with_varargs(*values: str) -> str:\n"
        "    return values[0]\n\n"
        "def with_kwargs(**values: str) -> str:\n"
        "    return values['x']\n",
        encoding="utf-8",
    )

    with pytest.raises(SchemaGenerationError):
        resolver.discover_file(unsupported)
    with pytest.raises(ImportError):
        resolver.discover_module("mcpme_missing_test_module")

    module_source = tmp_path / "helpers.py"
    module_source.write_text(
        "from enum import Enum\n"
        "from pathlib import Path\n\n"
        "class Mode(Enum):\n"
        "    FINE = 'fine'\n\n"
        "def helper(label: str = 'mesh') -> str:\n"
        "    return label\n",
        encoding="utf-8",
    )
    module = resolver._load_source_module(module_source.resolve(), None)
    enum_node = ast.parse("Mode.FINE", mode="eval").body
    path_node = ast.parse("Path('deck.inp')", mode="eval").body
    dict_node = ast.parse("dict[int, str]", mode="eval").body

    assert resolver._literal_value(module, enum_node) == "fine"
    assert resolver._literal_value(module, path_node) == "deck.inp"
    with pytest.raises(SchemaGenerationError):
        resolver._schema_from_annotation_node(module, dict_node)

    function_node = next(
        child
        for child in module.tree.body
        if isinstance(child, ast.FunctionDef) and child.name == "helper"
    )
    defaults = _parameter_defaults(function_node)
    assert defaults["label"] is not None
    assert _literal_str_sequence(ast.parse("['a', 'b']", mode="eval").body) == ("a", "b")
    assert _literal_str_sequence(ast.parse("[UNKNOWN]", mode="eval").body) is None

    loaded_module = load_module_from_path(module_source, fresh=True)
    resolved = resolve_qualname(loaded_module, "helper")
    assert callable(resolved)
    with pytest.raises(ValueError):
        resolve_qualname(loaded_module, "<locals>.helper")


def test_static_python_resolver_supports_reexported_class_annotations_and_new_container_names(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resolver should follow same-package class re-exports and newer container aliases."""

    package_dir = tmp_path / "source_types_pkg"
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text(
        '__all__ = ["run_case"]\nfrom .api import run_case\n',
        encoding="utf-8",
    )
    (package_dir / "models.py").write_text(
        "from dataclasses import dataclass\n\n@dataclass\nclass Config:\n    deck: str\n",
        encoding="utf-8",
    )
    (package_dir / "shared.py").write_text(
        "from .models import Config\n",
        encoding="utf-8",
    )
    (package_dir / "api.py").write_text(
        "from collections.abc import Mapping, Sequence\n"
        "from os import PathLike\n"
        "from numpy.typing import NDArray\n"
        "from .shared import Config\n\n"
        "def run_case(\n"
        "    config: Config,\n"
        "    deck: PathLike[str],\n"
        "    samples: Sequence[int],\n"
        "    weights: Mapping[str, float],\n"
        "    values: NDArray,\n"
        ") -> Config:\n"
        '    """Run a typed case.\n\n'
        "    :param config: Case config.\n"
        "    :param deck: Input deck path.\n"
        "    :param samples: Sample identifiers.\n"
        "    :param weights: Weight mapping.\n"
        "    :param values: Numeric values.\n"
        "    :returns: Echoed config.\n"
        '    """\n'
        "    return config\n",
        encoding="utf-8",
    )

    monkeypatch.syspath_prepend(str(tmp_path))
    resolver = StaticPythonResolver()
    discovered = resolver.discover_module("source_types_pkg")
    assert find_module_source_path("source_types_pkg.api") == (package_dir / "api.py").resolve()

    input_schema = discovered[0].tool.input_schema["properties"]
    assert input_schema["config"]["type"] == "object"
    assert input_schema["deck"]["format"] == "path"
    assert input_schema["samples"]["type"] == "array"
    assert input_schema["samples"]["items"] == {"type": "integer"}
    assert input_schema["weights"]["additionalProperties"]["type"] == "number"
    assert input_schema["values"]["type"] == "array"
    assert input_schema["values"]["items"] == {"type": "number"}
    assert discovered[0].tool.output_schema == {
        "type": "object",
        "properties": {"deck": {"type": "string"}},
        "required": ["deck"],
    }

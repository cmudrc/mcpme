"""Focused tests for internal package and CLI scaffolding helpers."""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Annotated, Any

import pytest

from mcpme._scaffold import (
    _annotation_source,
    _camel_to_snake,
    _capture_help_text,
    _class_close_docstring,
    _class_create_docstring,
    _class_method_docstring,
    _ClassSpec,
    _CliParameter,
    _command_invocation_lines,
    _command_parameter_source,
    _command_signature_lines,
    _default_source,
    _discover_module_names,
    _docstring_lines,
    _function_docstring,
    _FunctionSpec,
    _infer_cli_value_annotation,
    _module_qualifier,
    _named_command_docstring,
    _parameter_source,
    _parse_bool_token,
    _parse_command_parameters,
    _parse_default_from_description,
    _parse_number_token,
    _parse_option_parameter,
    _parse_positional_parameter,
    _parse_usage_required_options,
    _render_class_wrappers,
    _render_command_facade,
    _render_function_wrapper,
    _sanitize_name,
    _split_help_columns,
    _supports_named_wrapper,
    scaffold_command,
    scaffold_package,
)


def test_scaffold_command_reports_help_capture_failure(tmp_path: Path) -> None:
    output_path = tmp_path / "generated.py"
    report = scaffold_command(("/definitely/missing/tool",), output_path)

    assert report.generated_tools[0].style == "argv"
    assert "help capture failed" in report.skipped[0].reason
    assert "argv: list[str] | None = None" in output_path.read_text(encoding="utf-8")


def test_discover_module_names_tracks_internal_and_failed_submodules(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package_dir = tmp_path / "sample_pkg"
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text("__all__ = []\n", encoding="utf-8")
    (package_dir / "_internal.py").write_text("", encoding="utf-8")
    (package_dir / "bad.py").write_text("raise RuntimeError('boom')\n", encoding="utf-8")
    (package_dir / "good.py").write_text("", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))

    module_names, skipped = _discover_module_names(
        "sample_pkg",
        include_submodules=True,
        max_modules=2,
    )

    assert module_names == ["sample_pkg", "sample_pkg.good"]
    reasons = {entry.reason for entry in skipped}
    assert "submodule path is internal" in reasons
    assert any(reason.startswith("submodule import failed:") for reason in reasons)


def test_scaffold_package_skips_classes_without_signatures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package_dir = tmp_path / "builtin_pkg"
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text(
        "from collections import defaultdict\n\n__all__ = ['defaultdict']\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    package_report = scaffold_package("builtin_pkg", tmp_path / "builtin_facade.py")
    assert package_report.generated_tools == ()
    assert package_report.skipped[0].reason.startswith("class signature inspection failed:")


def test_scaffold_helper_functions_cover_cli_parser_edges() -> None:
    help_text = (
        "usage: tool --count COUNT [--verbose] name\n\n"
        "positional arguments:\n"
        "  name          Case name.\n\n"
        "options:\n"
        "  --count COUNT Number of iterations. required.\n"
        "  --verbose     Enable verbose mode.\n"
        "  -h, --help    show this help message and exit\n"
    )

    parsed = _parse_command_parameters(help_text)
    assert [parameter.name for parameter in parsed] == ["name", "count", "verbose"]
    assert _parse_usage_required_options(help_text) == {"--count"}
    assert _split_help_columns("  --flag    Enable flag.") == ("--flag", "Enable flag.")
    assert _split_help_columns("") is None
    assert _parse_option_parameter("--help", "", required_options=set()) is None
    assert _parse_option_parameter("???", "", required_options=set()) is None
    assert (
        _parse_positional_parameter(
            "!!!",
            "",
        )
        is None
    )
    assert _parse_default_from_description("default: 3.5") == 3.5
    assert _parse_default_from_description("defaults to yes") is True
    assert _parse_default_from_description("default: none") is None
    assert _parse_default_from_description("no default here") is not None
    assert _parse_bool_token("enabled") is True
    assert _parse_bool_token("disabled") is False
    assert _parse_bool_token("maybe") is None
    assert _parse_number_token("12") == 12
    assert _parse_number_token("1.5") == 1.5
    assert _parse_number_token("abc") is None
    assert _infer_cli_value_annotation("count", object()) == "int"
    assert _infer_cli_value_annotation("scale", object()) == "float"
    assert _infer_cli_value_annotation(None, object()) == "str"
    assert _capture_help_text(("/definitely/missing/tool",), timeout_seconds=0.1) is None


def test_scaffold_annotation_and_render_helpers_cover_branches() -> None:
    def keyword_only(*, path: Path, labels: list[str], extra: dict[str, int] | None = None) -> None:
        return None

    signature = inspect.signature(keyword_only)
    parameter_source = _parameter_source(tuple(signature.parameters.values()))
    assert parameter_source.startswith("*, path: Path")
    assert "labels: list[str]" in parameter_source
    assert "extra: dict[str, int] | None = None" in parameter_source

    assert _annotation_source(Any) == "Any"
    assert _annotation_source(Annotated[Path, "file"]) == "Path"
    assert _annotation_source(list[int]) == "list[int]"
    assert _annotation_source(dict[int, str]) == "dict[str, Any]"
    assert _annotation_source(dict[str, int]) == "dict[str, int]"
    assert _annotation_source(int | None) == "int | Any"

    assert _default_source(b"abc") == "b'abc'"
    assert _default_source(object()) is None
    assert _camel_to_snake("CycleModel") == "cycle_model"
    assert _module_qualifier("solver_pkg.submodule", "solver_pkg") == "submodule"
    assert _sanitize_name("mesh-tool!") == "mesh_tool"

    assert _supports_named_wrapper(signature) is True
    unsupported = inspect.Signature(
        parameters=(
            inspect.Parameter(
                "payload",
                inspect.Parameter.POSITIONAL_ONLY,
                annotation=int,
            ),
        )
    )
    assert _supports_named_wrapper(unsupported) is False

    bad_default_signature = inspect.Signature(
        parameters=(
            inspect.Parameter(
                "payload",
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                annotation=int,
                default=object(),
            ),
        )
    )
    assert _supports_named_wrapper(bad_default_signature) is False
    with pytest.raises(ValueError):
        _parameter_source(tuple(bad_default_signature.parameters.values()))


def test_scaffold_render_helpers_cover_args_kwargs_and_named_branches() -> None:
    named_spec = _FunctionSpec(
        name="solve",
        module_name="demo_pkg.core",
        qualname="solve",
        summary="Solve a case.",
        signature_text="solve(mesh_size: int = 2)",
        param_descriptions={"mesh_size": "Mesh size."},
        style="named",
        parameters=(
            inspect.Parameter(
                "mesh_size",
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                annotation=int,
                default=2,
            ),
        ),
    )
    args_spec = _FunctionSpec(
        name="legacy_call",
        module_name="demo_pkg.core",
        qualname="legacy_call",
        summary="Legacy call.",
        signature_text="legacy_call(*args, **kwargs)",
        param_descriptions={},
        style="args_kwargs",
        parameters=(),
    )
    class_spec = _ClassSpec(
        create_name="create_counter_session",
        close_name="close_counter_session",
        class_name="CounterSession",
        module_name="demo_pkg.core",
        qualname="CounterSession",
        summary="Create counter session.",
        constructor_signature_text="CounterSession(start: int = 0)",
        constructor_param_descriptions={"start": "Starting value."},
        constructor_style="args_kwargs",
        constructor_parameters=(),
        method_specs=(
            _FunctionSpec(
                name="counter_session_increment",
                module_name="demo_pkg.core",
                qualname="CounterSession.increment",
                summary="Increment the counter.",
                signature_text="increment(self, amount: int = 1)",
                param_descriptions={"amount": "Increment amount."},
                style="args_kwargs",
                parameters=(),
            ),
        ),
    )
    cli_parameter = _CliParameter(
        name="verbose",
        positional=False,
        syntax="--verbose",
        emitted_option="--verbose",
        annotation_source="bool",
        required=False,
        default_source="False",
        description="Verbose mode.",
        takes_value=False,
    )
    inverted_parameter = _CliParameter(
        name="cache",
        positional=False,
        syntax="--no-cache",
        emitted_option="--no-cache",
        annotation_source="bool",
        required=False,
        default_source="True",
        description="Disable cache.",
        takes_value=False,
        inverted_boolean=True,
    )

    assert "target = _resolve_symbol" in "\n".join(_render_function_wrapper(named_spec))
    assert "kwargs: dict[str, Any]" in "\n".join(_render_function_wrapper(args_spec))
    rendered_class = "\n".join(_render_class_wrappers(class_spec))
    assert "create_counter_session" in rendered_class
    assert "args: list[Any] | None = None" in rendered_class

    assert "Original signature" in _function_docstring(named_spec, payload_style=False)
    assert "kwargs: Optional keyword constructor arguments." in _class_create_docstring(
        class_spec,
        payload_style=True,
    )
    assert "args: Optional positional method arguments." in _class_method_docstring(
        class_spec,
        class_spec.method_specs[0],
        payload_style=True,
    )
    assert "Session-close metadata." in _class_close_docstring(class_spec)
    assert _docstring_lines("Line 1\nLine 2", indent="    ")[0] == '    """'

    named_command = _render_command_facade(
        command=("tool",),
        function_name="run_tool",
        help_text="usage: tool [--verbose]",
        parameters=(cli_parameter, inverted_parameter),
    )
    assert "extra_argv" in named_command
    assert "--no-cache" in named_command

    argv_command = _render_command_facade(
        command=("tool",),
        function_name="run_tool",
        help_text=None,
        parameters=(),
    )
    assert "argv: list[str] | None = None" in argv_command

    assert _command_signature_lines((cli_parameter,))[0] == "    verbose: bool = False,"
    assert _command_parameter_source(cli_parameter) == "verbose: bool = False"
    assert "Mapped from ``--verbose``." in _named_command_docstring(
        command=("tool",),
        parameters=(cli_parameter,),
        help_section="",
    )
    invocation_lines = _command_invocation_lines((cli_parameter, inverted_parameter))
    assert "    if verbose:" in invocation_lines
    assert "    if not cache:" in invocation_lines

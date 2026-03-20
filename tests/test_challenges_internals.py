"""Focused tests for internal live challenge helpers."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from mcpme._challenges import (
    ChallengeAggregate,
    ChallengeCatalogError,
    ChallengeIngestion,
    ChallengeProbe,
    ChallengeRenderedFile,
    ChallengeResult,
    ChallengeSpec,
    ChallengeTarget,
    ChallengeWorkflowStep,
    _badge_color,
    _base_context,
    _coerce_capture_name,
    _coerce_json_path,
    _extract_path_value,
    _normalize_command_scaffold_options,
    _normalize_package_scaffold_options,
    _optional_table,
    _parse_command_sequence_list,
    _parse_command_tokens,
    _parse_content_json,
    _parse_expectation_table,
    _parse_import_list,
    _parse_ingestion,
    _parse_rendered_files,
    _parse_string_tuple,
    _path_tokens,
    _probe_availability,
    _render_command_target,
    _render_package_target,
    _render_string,
    _render_value,
    _require_string,
    _require_table,
    _resolve_expected_path,
    _run_scaffold,
    _tuple_from_iterable_of_strings,
    _validate_ingestion,
    _validate_step_result,
    write_junit_xml,
    write_summary_markdown,
)
from mcpme.execution import ToolExecutionResult


def test_challenge_parser_and_rendering_helpers_cover_error_paths(tmp_path: Path) -> None:
    """Catalog and rendering helpers should fail clearly on malformed input."""
    fake_path = tmp_path / "challenge.toml"

    assert _parse_command_tokens("gmsh -3", fake_path) == ("gmsh", "-3")
    assert _parse_command_sequence_list([["gmsh"], "python tool.py"], fake_path) == (
        ("gmsh",),
        ("python", "tool.py"),
    )
    assert _parse_import_list(["demo.pkg"], fake_path) == ("demo.pkg",)
    assert _parse_string_tuple(["a", "b"], fake_path) == ("a", "b")
    assert _parse_ingestion(
        {"min_generated_tools": 2, "required_tools": ["alpha", "beta"]},
        fake_path,
    ) == ChallengeIngestion(min_generated_tools=2, required_tools=("alpha", "beta"))
    assert _parse_rendered_files(
        [{"source": "fixtures/demo.in", "destination": "{challenge_artifact_dir}/demo.txt"}],
        fake_path,
    ) == (
        ChallengeRenderedFile(
            source="fixtures/demo.in",
            destination="{challenge_artifact_dir}/demo.txt",
        ),
    )
    assert _parse_expectation_table({"beta": 2, "alpha": 1}, fake_path) == {
        "alpha": 1,
        "beta": 2,
    }
    assert _require_string({"name": "value"}, "name", fake_path) == "value"
    assert _require_table({"section": {"value": 1}}, "section", fake_path) == {"value": 1}
    assert _optional_table({}, "missing") == {}
    assert _coerce_capture_name("session_id", fake_path) == "session_id"
    assert _coerce_json_path("result.id", fake_path) == "result.id"
    assert _tuple_from_iterable_of_strings(["alpha"], "field") == ("alpha",)

    context = {"root": "/tmp/root", "name": "demo"}
    assert _render_string("{root}/{name}", context) == "/tmp/root/demo"
    assert _render_value({"path": "{root}", "items": ["{name}"]}, context) == {
        "path": "/tmp/root",
        "items": ["demo"],
    }
    assert _render_command_target(ChallengeTarget(kind="command", value="tool -h"), context) == (
        "tool",
        "-h",
    )
    assert _render_command_target(
        ChallengeTarget(kind="command", value=("tool", "{name}")),
        context,
    ) == ("tool", "demo")
    assert _path_tokens("items[1].name") == ("items", 1, "name")
    assert _extract_path_value({"items": [{"name": "a"}, {"name": "b"}]}, "items[1].name") == "b"
    assert _resolve_expected_path("out.txt", tmp_path) == tmp_path / "out.txt"
    assert _resolve_expected_path(str((tmp_path / "abs.txt").resolve()), tmp_path).is_absolute()

    empty_aggregate = ChallengeAggregate(
        suite_name="suite",
        selected_tier="gha_subset",
        results=(),
    )
    assert _badge_color(empty_aggregate) == "#9f9f9f"

    with pytest.raises(ChallengeCatalogError):
        _parse_command_tokens(3, fake_path)
    with pytest.raises(ChallengeCatalogError):
        _parse_command_sequence_list("gmsh", fake_path)
    with pytest.raises(ChallengeCatalogError):
        _parse_string_tuple("value", fake_path)
    with pytest.raises(ChallengeCatalogError):
        _parse_rendered_files("fixtures/demo.in", fake_path)
    with pytest.raises(ChallengeCatalogError):
        _parse_ingestion({"min_generated_tools": -1}, fake_path)
    with pytest.raises(ChallengeCatalogError):
        _parse_expectation_table([], fake_path)
    with pytest.raises(ChallengeCatalogError):
        _require_string({"name": ""}, "name", fake_path)
    with pytest.raises(ChallengeCatalogError):
        _require_table({"section": []}, "section", fake_path)
    with pytest.raises(ChallengeCatalogError):
        _optional_table({"section": []}, "section")
    with pytest.raises(ChallengeCatalogError):
        _coerce_capture_name("", fake_path)
    with pytest.raises(ChallengeCatalogError):
        _coerce_json_path("", fake_path)
    with pytest.raises(ChallengeCatalogError):
        _tuple_from_iterable_of_strings("alpha", "field")
    with pytest.raises(ChallengeCatalogError):
        _render_string("{missing}", context)
    with pytest.raises(ChallengeCatalogError):
        _render_package_target(ChallengeTarget(kind="package", value=("bad",)), context)
    with pytest.raises(ChallengeCatalogError):
        _path_tokens("...")


def test_challenge_validation_helpers_cover_failure_modes(tmp_path: Path) -> None:
    """Step validation and availability probes should return explicit failures."""
    json_result = ToolExecutionResult(
        content=({"type": "text", "text": json.dumps({"session_id": "abc", "value": 2})},),
        structured_content={"value": 2},
        artifact_dir=tmp_path / "artifacts",
    )
    plain_result = ToolExecutionResult(content=({"type": "text", "text": "plain"},))
    empty_file = tmp_path / "empty.txt"
    empty_file.write_text("", encoding="utf-8")

    assert (
        _validate_step_result(
            result=plain_result,
            step=ChallengeWorkflowStep(tool="tool", expect_tool_error=True),
            context={},
            challenge_dir=tmp_path,
        ).status
        == "failed"
    )
    assert (
        _validate_step_result(
            result=plain_result,
            step=ChallengeWorkflowStep(tool="tool", expect_text_contains=("missing",)),
            context={},
            challenge_dir=tmp_path,
        ).status
        == "failed"
    )
    assert (
        _validate_step_result(
            result=plain_result,
            step=ChallengeWorkflowStep(tool="tool", expect_json_fields={"value": 1}),
            context={},
            challenge_dir=tmp_path,
        ).status
        == "failed"
    )
    assert (
        _validate_step_result(
            result=plain_result,
            step=ChallengeWorkflowStep(tool="tool", expect_structured_fields={"value": 1}),
            context={},
            challenge_dir=tmp_path,
        ).status
        == "failed"
    )
    assert (
        _validate_step_result(
            result=json_result,
            step=ChallengeWorkflowStep(tool="tool", expect_files_exist=("missing.txt",)),
            context={},
            challenge_dir=tmp_path,
        ).status
        == "failed"
    )
    assert (
        _validate_step_result(
            result=json_result,
            step=ChallengeWorkflowStep(tool="tool", expect_files_nonempty=(str(empty_file),)),
            context={},
            challenge_dir=tmp_path,
        ).status
        == "failed"
    )
    assert (
        _validate_step_result(
            result=json_result,
            step=ChallengeWorkflowStep(tool="tool", expect_files_missing=(str(empty_file),)),
            context={},
            challenge_dir=tmp_path,
        ).status
        == "failed"
    )
    assert (
        _validate_step_result(
            result=plain_result,
            step=ChallengeWorkflowStep(tool="tool", capture_json={"session_id": "session_id"}),
            context={},
            challenge_dir=tmp_path,
        ).status
        == "failed"
    )
    context: dict[str, object] = {}
    success = _validate_step_result(
        result=json_result,
        step=ChallengeWorkflowStep(
            tool="tool",
            expect_json_fields={"value": 2},
            expect_structured_fields={"value": 2},
            capture_json={"captured_session": "session_id"},
        ),
        context=context,
        challenge_dir=tmp_path,
    )
    assert success.status == "passed"
    assert context["captured_session"] == "abc"
    assert _parse_content_json(json_result) == {"session_id": "abc", "value": 2}
    assert _parse_content_json(plain_result) is None

    missing_import_spec = ChallengeSpec(
        id="missing_import",
        title="Missing import",
        tier="gha_subset",
        style="package",
        slice="systems",
        target=ChallengeTarget(kind="package", value="missing_pkg"),
        probe=ChallengeProbe(imports=("missing_pkg",)),
        scaffold_kind="package",
        scaffold_options={},
        workflow_steps=(ChallengeWorkflowStep(tool="tool"),),
    )
    missing_path_spec = ChallengeSpec(
        id="missing_path",
        title="Missing path",
        tier="gha_subset",
        style="command",
        slice="systems",
        target=ChallengeTarget(kind="command", value=("/missing/tool",)),
        probe=ChallengeProbe(commands=(("/missing/tool",),)),
        scaffold_kind="command",
        scaffold_options={},
        workflow_steps=(ChallengeWorkflowStep(tool="tool"),),
    )
    assert "import failed" in _probe_availability(missing_import_spec, {"venv_bin_dir": ""})  # type: ignore[arg-type]
    assert "missing" in _probe_availability(missing_path_spec, {"venv_bin_dir": ""})  # type: ignore[arg-type]
    message = _validate_ingestion(
        ChallengeIngestion(min_generated_tools=2, required_tools=("alpha", "beta")),
        ("alpha",),
    )
    assert message is not None
    assert "expected at least 2 generated tools, got 1" in message
    assert "missing required generated tools ['beta']" in message
    assert _validate_ingestion(ChallengeIngestion(required_tools=("alpha",)), ("alpha",)) is None


def test_base_context_preserves_active_python_executable_path(tmp_path: Path) -> None:
    """The challenge template context should preserve the active interpreter path."""
    context = _base_context(
        repo_root=tmp_path,
        challenge_dir=tmp_path / "artifacts",
        fixture_dir=tmp_path / "fixtures",
    )

    assert context["python_executable"] == sys.executable


def test_challenge_scaffold_helpers_and_report_writers_cover_remaining_branches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Command scaffolding helpers and report writers should work together."""
    script_path = tmp_path / "echo_cli.py"
    script_path.write_text(
        "import json\n"
        "import sys\n\n"
        "if '-h' in sys.argv[1:]:\n"
        "    print('usage: echo_cli.py --value VALUE')\n"
        "    print('\\noptions:')\n"
        "    print('  --value VALUE  Value to echo.')\n"
        "    raise SystemExit(0)\n"
        "value = sys.argv[sys.argv.index('--value') + 1]\n"
        "print(json.dumps({'value': value}))\n",
        encoding="utf-8",
    )

    command_spec = ChallengeSpec(
        id="echo_cli",
        title="Echo CLI",
        tier="gha_subset",
        style="command",
        slice="systems",
        target=ChallengeTarget(kind="command", value=(sys.executable, str(script_path))),
        probe=ChallengeProbe(),
        scaffold_kind="command",
        scaffold_options={"function_name": "run_echo", "help_probe_args": ["-h"]},
        workflow_steps=(ChallengeWorkflowStep(tool="run_echo"),),
    )
    context = {
        "repo_root": str(tmp_path),
        "challenge_root": str(tmp_path / "challenges"),
        "challenge_artifact_dir": str(tmp_path / "artifacts"),
        "challenge_fixture_dir": str(tmp_path / "fixtures"),
        "python_executable": sys.executable,
        "venv_bin_dir": str(Path(sys.prefix) / "bin"),
        "pathsep": os.pathsep,
        "env_PATH": "",
    }
    report = _run_scaffold(
        command_spec,
        scaffold_path=tmp_path / "echo_facade.py",
        context=context,
    )
    assert report.generated_tools[0].name == "run_echo"
    assert _normalize_command_scaffold_options({"help_probe_args": ["-h"]}) == {
        "help_probe_args": ("-h",)
    }
    assert _normalize_package_scaffold_options(
        {"symbol_include_patterns": ["^tool$"], "module_exclude_patterns": ["^internal$"]}
    ) == {
        "symbol_include_patterns": ("^tool$",),
        "module_exclude_patterns": ("^internal$",),
    }

    aggregate = ChallengeAggregate(
        suite_name="suite",
        selected_tier="all",
        results=(
            ChallengeResult(
                id="pass",
                title="Pass",
                tier="gha_subset",
                style="package",
                slice="systems",
                status="passed",
                message="ok",
            ),
            ChallengeResult(
                id="fail",
                title="Fail",
                tier="gha_subset",
                style="command",
                slice="systems",
                status="failed",
                message="boom",
            ),
            ChallengeResult(
                id="skip",
                title="Skip",
                tier="local_full",
                style="command",
                slice="systems",
                status="skipped_unavailable",
                message="missing",
            ),
        ),
    )
    junit_path = tmp_path / "junit.xml"
    summary_path = tmp_path / "summary.md"
    write_junit_xml(aggregate, junit_path)
    write_summary_markdown(aggregate, summary_path)
    junit_text = junit_path.read_text(encoding="utf-8")
    assert "<failure" in junit_text
    assert "<skipped" in junit_text
    assert "challenge.gha_subset.pass.medium" in junit_text
    assert "skip" in summary_path.read_text(encoding="utf-8")

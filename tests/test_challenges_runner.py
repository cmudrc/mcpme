"""Tests for the live challenge runner and report generation."""

from __future__ import annotations

import json
from pathlib import Path

from mcpcraft._challenges import (
    ChallengeAggregate,
    ChallengeProbe,
    ChallengeRenderedFile,
    ChallengeResult,
    ChallengeSpec,
    ChallengeStepResult,
    ChallengeTarget,
    ChallengeWorkflowStep,
    render_badge_svg,
    render_summary_markdown,
    run_challenge_suite,
    write_junit_xml,
    write_metrics_json,
)


def test_run_challenge_suite_executes_multi_step_package_flow(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    """The runner should scaffold, execute, capture context, and report success."""
    package_dir = tmp_path / "challenge_pkg"
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text(
        '"""Challenge package."""\n'
        "class Counter:\n"
        '    """Simple counter.\n\n'
        "    :param start: Starting value.\n"
        '    """\n'
        "    def __init__(self, start: int = 0) -> None:\n"
        "        self.value = start\n\n"
        "    def increment(self, amount: int = 1) -> int:\n"
        '        """Increment the counter.\n\n'
        "        :param amount: Increment amount.\n"
        "        :returns: Updated value.\n"
        '        """\n'
        "        self.value += amount\n"
        "        return self.value\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    spec = ChallengeSpec(
        id="counter_pkg",
        title="Counter package",
        tier="gha_subset",
        style="package",
        slice="systems",
        target=ChallengeTarget(kind="package", value="challenge_pkg"),
        probe=ChallengeProbe(imports=("challenge_pkg",)),
        scaffold_kind="package",
        scaffold_options={"symbol_include_patterns": ["^Counter$"]},
        workflow_steps=(
            ChallengeWorkflowStep(
                tool="create_counter",
                arguments={"start": 4},
                capture_json={"counter_session_id": "session_id"},
            ),
            ChallengeWorkflowStep(
                tool="counter_increment",
                arguments={"session_id": "{counter_session_id}", "amount": 3},
                expect_json_fields={"$": 7},
            ),
            ChallengeWorkflowStep(
                tool="close_counter",
                arguments={"session_id": "{counter_session_id}"},
                expect_structured_fields={"success": True},
            ),
        ),
    )

    aggregate = run_challenge_suite(
        (spec,),
        repo_root=tmp_path,
        artifact_root=tmp_path / "artifacts",
        selected_tier="gha_subset",
    )

    assert aggregate.total == 1
    assert aggregate.passed == 1
    result = aggregate.results[0]
    assert result.status == "passed"
    assert result.generated_tools == ("create_counter", "counter_increment", "close_counter")
    assert result.steps[0].captured["counter_session_id"]

    metrics_path = tmp_path / "artifacts" / "metrics.json"
    junit_path = tmp_path / "artifacts" / "junit.xml"
    write_metrics_json(aggregate, metrics_path)
    write_junit_xml(aggregate, junit_path)

    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert metrics["summary"] == {"failed": 0, "passed": 1, "skippedUnavailable": 0, "total": 1}
    junit_text = junit_path.read_text(encoding="utf-8")
    assert 'tests="1"' in junit_text
    assert 'failures="0"' in junit_text


def test_run_challenge_suite_marks_unavailable_targets_as_skipped(tmp_path: Path) -> None:
    """Missing probe commands should become skipped-unavailable results."""
    spec = ChallengeSpec(
        id="missing_command",
        title="Missing command",
        tier="local_full",
        style="command",
        slice="aerodynamics",
        target=ChallengeTarget(kind="command", value=("definitely_missing_binary",)),
        probe=ChallengeProbe(commands=(("definitely_missing_binary",),)),
        scaffold_kind="command",
        scaffold_options={"function_name": "run_missing"},
        workflow_steps=(ChallengeWorkflowStep(tool="run_missing", arguments={}),),
    )

    aggregate = run_challenge_suite(
        (spec,),
        repo_root=tmp_path,
        artifact_root=tmp_path / "artifacts",
        selected_tier="all",
    )

    assert aggregate.skipped_unavailable == 1
    assert aggregate.results[0].status == "skipped_unavailable"
    assert "unavailable" in aggregate.results[0].message


def test_run_challenge_suite_can_select_specific_ids(tmp_path: Path) -> None:
    """The runner should allow one case to be exercised in isolation."""
    alpha = ChallengeSpec(
        id="alpha",
        title="Alpha",
        tier="gha_subset",
        style="command",
        slice="systems",
        target=ChallengeTarget(kind="command", value=("missing_alpha",)),
        probe=ChallengeProbe(commands=(("missing_alpha",),)),
        scaffold_kind="command",
        scaffold_options={},
        workflow_steps=(ChallengeWorkflowStep(tool="alpha"),),
    )
    beta = ChallengeSpec(
        id="beta",
        title="Beta",
        tier="gha_subset",
        style="command",
        slice="systems",
        target=ChallengeTarget(kind="command", value=("missing_beta",)),
        probe=ChallengeProbe(commands=(("missing_beta",),)),
        scaffold_kind="command",
        scaffold_options={},
        workflow_steps=(ChallengeWorkflowStep(tool="beta"),),
    )

    aggregate = run_challenge_suite(
        (alpha, beta),
        repo_root=tmp_path,
        artifact_root=tmp_path / "artifacts",
        selected_tier="gha_subset",
        selected_ids=("beta",),
    )

    assert aggregate.total == 1
    assert aggregate.results[0].id == "beta"


def test_run_challenge_suite_isolates_upstream_relative_outputs(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    """Live package workflow steps should run inside the per-challenge artifact directory."""
    package_dir = tmp_path / "cwd_pkg"
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text(
        '"""Challenge package that writes relative outputs."""\n'
        "from pathlib import Path\n\n"
        "def emit_relative_file(name: str) -> str:\n"
        '    """Write a relative output file.\n\n'
        "    :param name: Relative filename to create.\n"
        "    :returns: The created filename.\n"
        '    """\n'
        "    Path(name).write_text('ok', encoding='utf-8')\n"
        "    return name\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    file_name = f"{tmp_path.name}-challenge-output.txt"
    original_cwd = Path.cwd()
    repo_side_output = original_cwd / file_name

    spec = ChallengeSpec(
        id="cwd_pkg",
        title="CWD package",
        tier="gha_subset",
        style="package",
        slice="systems",
        target=ChallengeTarget(kind="package", value="cwd_pkg"),
        probe=ChallengeProbe(imports=("cwd_pkg",)),
        scaffold_kind="package",
        scaffold_options={"symbol_include_patterns": ["^emit_relative_file$"]},
        workflow_steps=(
            ChallengeWorkflowStep(
                tool="emit_relative_file",
                arguments={"name": file_name},
                expect_files_nonempty=(file_name,),
            ),
        ),
    )

    aggregate = run_challenge_suite(
        (spec,),
        repo_root=tmp_path,
        artifact_root=tmp_path / "artifacts",
        selected_tier="gha_subset",
    )

    challenge_output = tmp_path / "artifacts" / "cwd_pkg" / file_name
    assert aggregate.results[0].status == "passed"
    assert challenge_output.read_text(encoding="utf-8") == "ok"
    assert not repo_side_output.exists()
    assert Path.cwd() == original_cwd


def test_run_challenge_suite_renders_setup_inputs_before_the_workflow(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    """Rendered setup files should be materialized before workflow execution."""
    package_dir = tmp_path / "reader_pkg"
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text(
        '"""Challenge package that reads a text file."""\n'
        "from pathlib import Path\n\n"
        "def read_text(path: str) -> str:\n"
        '    """Read a UTF-8 text file.\n\n'
        "    :param path: File path to read.\n"
        "    :returns: The file contents.\n"
        '    """\n'
        "    return Path(path).read_text(encoding='utf-8')\n",
        encoding="utf-8",
    )
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    (case_dir / "message.txt.in").write_text("workflow-ready {repo_root}", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))

    spec = ChallengeSpec(
        id="reader_pkg",
        title="Reader package",
        tier="gha_subset",
        style="package",
        slice="systems",
        target=ChallengeTarget(kind="package", value="reader_pkg"),
        probe=ChallengeProbe(imports=("reader_pkg",)),
        scaffold_kind="package",
        scaffold_options={"symbol_include_patterns": ["^read_text$"]},
        rendered_files=(
            ChallengeRenderedFile(
                source="message.txt.in",
                destination="{challenge_artifact_dir}/message.txt",
            ),
        ),
        workflow_steps=(
            ChallengeWorkflowStep(
                tool="read_text",
                arguments={"path": "{challenge_artifact_dir}/message.txt"},
                expect_text_contains=("workflow-ready", "{repo_root}"),
            ),
        ),
        case_dir=case_dir,
        catalog_path=case_dir / "challenge.toml",
    )

    aggregate = run_challenge_suite(
        (spec,),
        repo_root=tmp_path,
        artifact_root=tmp_path / "artifacts",
        selected_tier="gha_subset",
    )

    rendered_path = tmp_path / "artifacts" / "reader_pkg" / "message.txt"
    assert aggregate.results[0].status == "passed"
    assert rendered_path.read_text(encoding="utf-8").startswith("workflow-ready ")


def test_challenge_badge_and_summary_render_deterministically() -> None:
    """Badge and markdown summary output should reflect aggregate counts clearly."""
    aggregate = ChallengeAggregate(
        suite_name="live_raw_upstream",
        selected_tier="gha_subset",
        results=(
            ChallengeResult(
                id="alpha",
                title="Alpha",
                tier="gha_subset",
                style="package",
                slice="systems",
                status="passed",
                message="ok",
                steps=(
                    ChallengeStepResult(
                        tool="alpha",
                        label="alpha",
                        status="passed",
                        message="ok",
                    ),
                ),
            ),
            ChallengeResult(
                id="beta",
                title="Beta",
                tier="gha_subset",
                style="command",
                slice="aerodynamics",
                status="failed",
                message="boom",
            ),
        ),
    )

    badge = render_badge_svg(aggregate)
    summary = render_summary_markdown(aggregate)

    assert 'aria-label="Challenges Live: 1/2 pass"' in badge
    assert "| `alpha` | `gha_subset` | `passed` | ok |" in summary
    assert "| `beta` | `gha_subset` | `failed` | boom |" in summary

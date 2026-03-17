"""Tests for generated challenge README content."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from mcpme._challenges import (
    ChallengeExample,
    ChallengeIngestion,
    ChallengeProbe,
    ChallengeRenderedFile,
    ChallengeSpec,
    ChallengeTarget,
    ChallengeWorkflowStep,
)


def _load_module(path: Path) -> object:
    """Load one script module from disk for direct function testing."""
    spec = importlib.util.spec_from_file_location("generate_challenge_docs", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_challenge_doc_renderer_produces_self_contained_case_readme(tmp_path: Path) -> None:
    """Generated challenge docs should read like runnable worked examples."""
    repo_root = tmp_path
    case_dir = repo_root / "challenges" / "cases" / "demo_case"
    fixture_dir = case_dir / "fixtures"
    fixture_dir.mkdir(parents=True)
    (fixture_dir / "demo.txt").write_text("fixture", encoding="utf-8")
    catalog_path = case_dir / "challenge.toml"
    catalog_path.write_text('id = "demo_case"\n', encoding="utf-8")

    script_path = Path(__file__).resolve().parents[1] / "scripts" / "generate_challenge_docs.py"
    module = _load_module(script_path)
    spec = ChallengeSpec(
        id="demo_case",
        title="Demo Case",
        tier="gha_subset",
        style="package",
        slice="systems",
        target=ChallengeTarget(kind="package", value="demo.pkg"),
        probe=ChallengeProbe(imports=("demo.pkg",)),
        scaffold_kind="package",
        scaffold_options={},
        rendered_files=(
            ChallengeRenderedFile(
                source="fixtures/demo.in",
                destination="{challenge_artifact_dir}/demo.txt",
            ),
        ),
        workflow_steps=(
            ChallengeWorkflowStep(
                tool="run_demo",
                label="Run the demo tool",
                arguments={"message": "hello"},
                expect_text_contains=("hello",),
            ),
        ),
        ingestion=ChallengeIngestion(
            min_generated_tools=2,
            required_tools=("run_demo", "close_demo"),
        ),
        example=ChallengeExample(
            summary="Summarize one compact challenge.",
            motivation="Show why the challenge system doubles as documentation.",
            proves=("Case-local READMEs can be generated.",),
        ),
        catalog_path=catalog_path,
        case_dir=case_dir,
    )

    case_readme = module._render_case_readme(spec, repo_root)
    index_readme = module._render_challenge_index((spec,), repo_root)

    assert "Summarize one compact challenge." in case_readme
    assert "make challenge CASE=demo_case" in case_readme
    assert "demo_case/challenge.toml" in case_readme
    assert "demo_case/fixtures/demo.txt" in case_readme
    assert "Ingestion Breadth" in case_readme
    assert "Prepared Inputs" in case_readme
    assert "fixtures/demo.in" in case_readme
    assert "Minimum generated tools" in case_readme
    assert "close_demo" in case_readme
    assert "Run the demo tool" in case_readme
    assert "[`demo_case`](cases/demo_case/README.md)" in index_readme

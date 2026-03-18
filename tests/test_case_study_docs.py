"""Tests for generated case-study docs content."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_module(path: Path) -> object:
    """Load one script module from disk for direct function testing."""
    spec = importlib.util.spec_from_file_location("generate_case_study_docs", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_case_study_doc_renderer_produces_case_study_pages() -> None:
    """Generated docs should render a readable case-study index and page."""
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "generate_case_study_docs.py"
    module = _load_module(script_path)
    spec = module.CaseStudyDocSpec(
        case_dir_rel_path="case_studies/demo_case",
        slug="demo_case",
        title="Demo Case",
        ingest_rel_path="case_studies/demo_case/ingest.py",
        ingest_source_start_line=9,
        use_rel_path="case_studies/demo_case/use.py",
        use_source_start_line=21,
        sections={
            "Introduction": "Explain the real-upstream scenario.",
            "Preset Environment": "Show the checked-in source inputs.",
            "Technical Implementation": "Show the deterministic scaffold path.",
            "Expected Results": "Describe the JSON payload.",
            "Availability": "Explain the optional dependency story.",
            "References": "- ``README.md``",
        },
    )

    case_page = module._render_case_study_page(spec)
    index_page = module._render_case_studies_index([spec])

    assert "Demo Case" in case_page
    assert "Preset Environment" in case_page
    assert "Availability" in case_page
    assert "case_studies/demo_case/use.py" in case_page
    assert "case_studies/demo_case/ingest.py" in case_page
    assert ".. literalinclude:: ../../case_studies/demo_case/ingest.py" in case_page
    assert ".. literalinclude:: ../../case_studies/demo_case/use.py" in case_page
    assert "Case Studies" in index_page
    assert "demo_case" in index_page
    assert "Explain the real-upstream scenario." in index_page

"""Tests for generated real-world example docs content."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_module(path: Path) -> object:
    """Load one script module from disk for direct function testing."""
    spec = importlib.util.spec_from_file_location("generate_example_docs", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_real_world_doc_renderer_produces_real_world_pages() -> None:
    """Generated docs should render a readable real-world index and page."""
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "generate_example_docs.py"
    module = _load_module(script_path)
    spec = module.RealWorldExampleDocSpec(
        case_dir_rel_path="examples/real_world/demo_case",
        slug="demo_case",
        title="Demo Case",
        ingest_rel_path="examples/real_world/demo_case/ingest.py",
        ingest_source_start_line=9,
        serve_rel_path="examples/real_world/demo_case/serve.py",
        serve_source_start_line=15,
        use_rel_path="examples/real_world/demo_case/use.py",
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

    case_page = module._render_real_world_page(spec)
    index_page = module._render_real_world_index([spec])

    assert "Demo Case" in case_page
    assert "Preset Environment" in case_page
    assert "Availability" in case_page
    assert "examples/real_world/demo_case/use.py" in case_page
    assert "examples/real_world/demo_case/ingest.py" in case_page
    assert "examples/real_world/demo_case/serve.py" in case_page
    assert ".. literalinclude:: ../../../examples/real_world/demo_case/ingest.py" in case_page
    assert ".. literalinclude:: ../../../examples/real_world/demo_case/serve.py" in case_page
    assert ".. literalinclude:: ../../../examples/real_world/demo_case/use.py" in case_page
    assert "Real-World Examples" in index_page
    assert "demo_case" in index_page
    assert "Explain the real-upstream scenario." in index_page

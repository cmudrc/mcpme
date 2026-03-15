"""Boundary tests for example imports, docs contracts, and generated pages."""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES_ROOT = REPO_ROOT / "examples"
REQUIRED_DOC_SECTIONS = (
    "Introduction",
    "Technical Implementation",
    "Expected Results",
    "References",
)


def _collect_violations(*, pattern: re.Pattern[str], root: Path) -> list[str]:
    """Collect text matches for one forbidden pattern under a root."""
    violations: list[str] = []
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for line_number, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                violations.append(f"{path.relative_to(REPO_ROOT)}:{line_number}: {line.strip()}")
    return violations


def _iter_example_doc_lines() -> list[tuple[Path, list[str]]]:
    """Yield example paths and their module docstring lines."""
    docs: list[tuple[Path, list[str]]] = []
    for path in sorted(EXAMPLES_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts or path.name.startswith("_"):
            continue
        module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        docstring = ast.get_docstring(module, clean=False)
        docs.append(
            (
                path,
                docstring.splitlines() if isinstance(docstring, str) and docstring.strip() else [],
            )
        )
    return docs


def _extract_markdown_section_names(lines: list[str]) -> set[str]:
    """Extract canonical section names from a module docstring."""
    names: set[str] = set()
    for raw_line in lines:
        line = raw_line.strip()
        if line.startswith("## "):
            names.add(line[3:].strip())
    return names


def test_examples_import_only_the_public_package_root() -> None:
    """Examples should not import internal modules or deep package paths."""
    private_pattern = re.compile(r"^\s*(from|import)\s+mcpme\._")
    deep_module_pattern = re.compile(r"^\s*from\s+mcpme\.[A-Za-z0-9_]+")
    violations = _collect_violations(pattern=private_pattern, root=EXAMPLES_ROOT)
    violations.extend(_collect_violations(pattern=deep_module_pattern, root=EXAMPLES_ROOT))
    assert violations == [], "\n".join(violations)


def test_examples_include_canonical_module_doc_sections() -> None:
    """Every runnable example should carry the canonical generated-docs sections."""
    violations: list[str] = []
    for path, lines in _iter_example_doc_lines():
        present = _extract_markdown_section_names(lines)
        missing = [section for section in REQUIRED_DOC_SECTIONS if section not in present]
        if missing:
            violations.append(f"{path.relative_to(REPO_ROOT)}: missing sections {missing}")
    assert violations == [], "\n".join(violations)


def test_generated_example_docs_are_up_to_date() -> None:
    """Checked-in generated example docs should match current example docstrings."""
    completed = subprocess.run(
        [sys.executable, "scripts/generate_example_docs.py", "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, (
        "Generated example docs are out of date.\n"
        f"stdout:\n{completed.stdout}\n"
        f"stderr:\n{completed.stderr}"
    )

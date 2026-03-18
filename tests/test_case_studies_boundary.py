"""Boundary tests for case-study imports, docs contracts, and generated pages."""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CASE_STUDIES_ROOT = REPO_ROOT / "case_studies"
REQUIRED_DOC_SECTIONS = (
    "Introduction",
    "Preset Environment",
    "Technical Implementation",
    "Expected Results",
    "Availability",
    "References",
)


def _iter_case_study_dirs() -> list[Path]:
    """Return checked-in case-study directories with ingest/use entrypoints."""
    return [
        path
        for path in sorted(CASE_STUDIES_ROOT.iterdir())
        if path.is_dir()
        and not path.name.startswith("_")
        and path.name != "support"
        and (path / "ingest.py").exists()
        and (path / "serve.py").exists()
        and (path / "use.py").exists()
    ]


def _collect_violations(*, pattern: re.Pattern[str], root: Path) -> list[str]:
    """Collect text matches for one forbidden pattern under a root."""
    violations: list[str] = []
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts or "artifacts" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for line_number, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                violations.append(f"{path.relative_to(REPO_ROOT)}:{line_number}: {line.strip()}")
    return violations


def _iter_case_study_doc_lines() -> list[tuple[Path, list[str]]]:
    """Yield case-study `use.py` paths and their module docstring lines."""
    docs: list[tuple[Path, list[str]]] = []
    for case_dir in _iter_case_study_dirs():
        path = case_dir / "use.py"
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


def _expr_uses_artifact_root(expression: ast.AST) -> bool:
    """Return whether one AST expression clearly points at the artifact tree."""
    rendered = ast.unparse(expression)
    return any(
        token in rendered
        for token in ("ARTIFACT_ROOT", "STATE_PATH", "GENERATED_FACADE_PATH", "artifacts")
    )


def _iter_runtime_materialization_violations() -> list[str]:
    """Find case-study entrypoints that still materialize source inputs at runtime."""
    violations: list[str] = []
    for case_dir in _iter_case_study_dirs():
        for path in (case_dir / "ingest.py", case_dir / "serve.py", case_dir / "use.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if isinstance(node.func, ast.Attribute) and node.func.attr in {
                    "write_text",
                    "write_bytes",
                }:
                    if not _expr_uses_artifact_root(node.func.value):
                        violations.append(
                            f"{path.relative_to(REPO_ROOT)}:{node.lineno}: runtime file writes are "
                            "only allowed under ARTIFACT_ROOT in case-study entrypoints."
                        )
                    continue
                if isinstance(node.func, ast.Attribute) and node.func.attr == "mkdir":
                    if not _expr_uses_artifact_root(node.func.value):
                        violations.append(
                            f"{path.relative_to(REPO_ROOT)}:{node.lineno}: mkdir is only allowed "
                            "under ARTIFACT_ROOT in case-study entrypoints."
                        )
                    continue
                if isinstance(node.func, ast.Name) and node.func.id == "open":
                    mode_arg = node.args[1] if len(node.args) > 1 else None
                    path_arg = node.args[0] if node.args else None
                    for keyword in node.keywords:
                        if keyword.arg == "mode" and mode_arg is None:
                            mode_arg = keyword.value
                        if keyword.arg in {"file", "path"} and path_arg is None:
                            path_arg = keyword.value
                    if (
                        isinstance(mode_arg, ast.Constant)
                        and isinstance(mode_arg.value, str)
                        and any(flag in mode_arg.value for flag in ("w", "a", "x", "+"))
                        and path_arg is not None
                        and not _expr_uses_artifact_root(path_arg)
                    ):
                        violations.append(
                            f"{path.relative_to(REPO_ROOT)}:{node.lineno}: runtime file opens in "
                            "write mode are only allowed under ARTIFACT_ROOT in case-study "
                            "entrypoints."
                        )
    return violations


def test_case_studies_import_only_the_public_package_root() -> None:
    """Case studies should not import internal modules or deep package paths."""
    private_pattern = re.compile(r"^\s*(from|import)\s+mcpme\._")
    deep_module_pattern = re.compile(r"^\s*from\s+mcpme\.[A-Za-z0-9_]+")
    violations = _collect_violations(pattern=private_pattern, root=CASE_STUDIES_ROOT)
    violations.extend(_collect_violations(pattern=deep_module_pattern, root=CASE_STUDIES_ROOT))
    assert violations == [], "\n".join(violations)


def test_case_studies_include_canonical_module_doc_sections() -> None:
    """Every case study should carry the canonical generated-docs sections."""
    violations: list[str] = []
    for path, lines in _iter_case_study_doc_lines():
        present = _extract_markdown_section_names(lines)
        missing = [section for section in REQUIRED_DOC_SECTIONS if section not in present]
        if missing:
            violations.append(f"{path.relative_to(REPO_ROOT)}: missing sections {missing}")
    assert violations == [], "\n".join(violations)


def test_case_study_entrypoints_include_module_docstrings() -> None:
    """Every checked-in case-study entrypoint should have a module docstring."""
    violations: list[str] = []
    for case_dir in _iter_case_study_dirs():
        for path in (case_dir / "ingest.py", case_dir / "serve.py", case_dir / "use.py"):
            module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            docstring = ast.get_docstring(module, clean=False)
            if not isinstance(docstring, str) or not docstring.strip():
                violations.append(f"{path.relative_to(REPO_ROOT)}: missing module docstring")
    assert violations == [], "\n".join(violations)


def test_case_studies_do_not_materialize_support_inputs_at_runtime() -> None:
    """Case studies should keep support inputs checked in rather than writing them on the fly."""
    violations = _iter_runtime_materialization_violations()
    assert violations == [], "\n".join(violations)


def test_generated_case_study_docs_are_up_to_date() -> None:
    """Checked-in generated case-study docs should match current docstrings."""
    completed = subprocess.run(
        [sys.executable, "scripts/generate_case_study_docs.py", "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, (
        "Generated case-study docs are out of date.\n"
        f"stdout:\n{completed.stdout}\n"
        f"stderr:\n{completed.stderr}"
    )

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
    "Preset Environment",
    "Technical Implementation",
    "Expected Results",
    "References",
)


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


def _iter_example_doc_lines() -> list[tuple[Path, list[str]]]:
    """Yield example paths and their module docstring lines."""
    docs: list[tuple[Path, list[str]]] = []
    for path in sorted(EXAMPLES_ROOT.glob("*.py")):
        if path.name.startswith("_"):
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


def _expr_uses_artifact_root(expression: ast.AST) -> bool:
    """Return whether one AST expression clearly points at the artifact tree."""
    rendered = ast.unparse(expression)
    return "ARTIFACT_ROOT" in rendered or "artifacts" in rendered


def _iter_runtime_materialization_violations() -> list[str]:
    """Find example entrypoints that still materialize source inputs at runtime."""
    violations: list[str] = []
    for path in sorted(EXAMPLES_ROOT.glob("*.py")):
        if path.name.startswith("_"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Attribute) and node.func.attr in {
                "write_text",
                "write_bytes",
            }:
                violations.append(
                    f"{path.relative_to(REPO_ROOT)}:{node.lineno}: runtime file writes are not "
                    "allowed in example entrypoints."
                )
                continue
            if isinstance(node.func, ast.Attribute) and node.func.attr == "mkdir":
                if not _expr_uses_artifact_root(node.func.value):
                    violations.append(
                        f"{path.relative_to(REPO_ROOT)}:{node.lineno}: mkdir is only allowed "
                        "under ARTIFACT_ROOT in example entrypoints."
                    )
                continue
            if isinstance(node.func, ast.Name) and node.func.id == "open":
                mode_arg = node.args[1] if len(node.args) > 1 else None
                if mode_arg is None:
                    for keyword in node.keywords:
                        if keyword.arg == "mode":
                            mode_arg = keyword.value
                            break
                if (
                    isinstance(mode_arg, ast.Constant)
                    and isinstance(mode_arg.value, str)
                    and any(flag in mode_arg.value for flag in ("w", "a", "x", "+"))
                ):
                    violations.append(
                        f"{path.relative_to(REPO_ROOT)}:{node.lineno}: runtime file opens in "
                        "write mode are not allowed in example entrypoints."
                    )
    return violations


def test_examples_import_only_the_public_package_root() -> None:
    """Examples should not import internal modules or deep package paths."""
    private_pattern = re.compile(r"^\s*(from|import)\s+mcpwrap\._")
    deep_module_pattern = re.compile(r"^\s*from\s+mcpwrap\.[A-Za-z0-9_]+")
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


def test_examples_do_not_materialize_support_inputs_at_runtime() -> None:
    """Examples should keep support inputs checked in rather than writing them on the fly."""
    violations = _iter_runtime_materialization_violations()
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

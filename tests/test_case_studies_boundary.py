"""Boundary tests for real-world example imports, docs contracts, and pages."""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_WORLD_EXAMPLES_ROOT = REPO_ROOT / "examples" / "real_world"
REQUIRED_DOC_SECTIONS = (
    "Introduction",
    "Preset Environment",
    "Technical Implementation",
    "Expected Results",
    "Availability",
    "References",
)


def _iter_real_world_example_dirs() -> list[Path]:
    """Return checked-in real-world example directories with entrypoints."""
    return [
        path
        for path in sorted(REAL_WORLD_EXAMPLES_ROOT.iterdir())
        if path.is_dir()
        and not path.name.startswith("_")
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


def _iter_real_world_example_doc_lines() -> list[tuple[Path, list[str]]]:
    """Yield real-world example `use.py` paths and their module docstring lines."""
    docs: list[tuple[Path, list[str]]] = []
    for case_dir in _iter_real_world_example_dirs():
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
        for token in ("ARTIFACT_ROOT", "GENERATED_FACADE_PATH", "REPORT_PATH", "artifacts")
    )


def _iter_runtime_materialization_violations() -> list[str]:
    """Find real-world entrypoints that still materialize source inputs at runtime."""
    violations: list[str] = []
    for case_dir in _iter_real_world_example_dirs():
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
                            "only allowed under ARTIFACT_ROOT in real-world example entrypoints."
                        )
                    continue
                if isinstance(node.func, ast.Attribute) and node.func.attr == "mkdir":
                    if not _expr_uses_artifact_root(node.func.value):
                        violations.append(
                            f"{path.relative_to(REPO_ROOT)}:{node.lineno}: mkdir is only allowed "
                            "under ARTIFACT_ROOT in real-world example entrypoints."
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
                            "write mode are only allowed under ARTIFACT_ROOT in real-world "
                            "example entrypoints."
                        )
    return violations


def test_real_world_examples_import_only_the_public_package_root() -> None:
    """Real-world examples should not import internal modules or deep package paths."""
    private_pattern = re.compile(r"^\s*(from|import)\s+mcpcraft\._")
    deep_module_pattern = re.compile(r"^\s*from\s+mcpcraft\.[A-Za-z0-9_]+")
    violations = _collect_violations(pattern=private_pattern, root=REAL_WORLD_EXAMPLES_ROOT)
    violations.extend(
        _collect_violations(pattern=deep_module_pattern, root=REAL_WORLD_EXAMPLES_ROOT)
    )
    assert violations == [], "\n".join(violations)


def test_real_world_examples_include_canonical_module_doc_sections() -> None:
    """Every real-world example should carry the canonical generated-docs sections."""
    violations: list[str] = []
    for path, lines in _iter_real_world_example_doc_lines():
        present = _extract_markdown_section_names(lines)
        missing = [section for section in REQUIRED_DOC_SECTIONS if section not in present]
        if missing:
            violations.append(f"{path.relative_to(REPO_ROOT)}: missing sections {missing}")
    assert violations == [], "\n".join(violations)


def test_real_world_example_entrypoints_include_module_docstrings() -> None:
    """Every checked-in real-world example entrypoint should have a module docstring."""
    violations: list[str] = []
    for case_dir in _iter_real_world_example_dirs():
        for path in (case_dir / "ingest.py", case_dir / "serve.py", case_dir / "use.py"):
            module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            docstring = ast.get_docstring(module, clean=False)
            if not isinstance(docstring, str) or not docstring.strip():
                violations.append(f"{path.relative_to(REPO_ROOT)}: missing module docstring")
    assert violations == [], "\n".join(violations)


def test_real_world_examples_do_not_materialize_support_inputs_at_runtime() -> None:
    """Real-world examples should keep support inputs checked in at runtime."""
    violations = _iter_runtime_materialization_violations()
    assert violations == [], "\n".join(violations)


def test_generated_example_docs_include_real_world_examples() -> None:
    """Checked-in generated docs should match current real-world example docstrings."""
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

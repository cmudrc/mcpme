"""Validate public documentation consistency invariants.

The goal is to keep the public contract explicit:

- every curated top-level export is rendered in ``docs/api.rst``,
- user-facing docs do not drift toward internal modules,
- referenced example paths exist, and
- stale template-era package names do not leak back into the docs.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

SCAN_FILE_SUFFIXES = (".rst", ".md")
PUBLIC_PATH_PATTERN = re.compile(r"(examples/[A-Za-z0-9_./-]+\.(?:py|md|xml|json|toml|sh))")
API_AUTODOC_DIRECTIVE_PATTERN = re.compile(
    r"^\.\.\s+auto(?:class|data|function|attribute|exception)::\s+"
    r"mcpcraft\.([A-Za-z_][A-Za-z0-9_]*)\s*$",
    re.MULTILINE,
)
INTERNAL_MODULE_PATTERN = re.compile(r"\bmcpcraft\._[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*\b")
STALE_NAME_PATTERN = re.compile(r"\bpython_template\b|\bsrc/python_template\b")
TOCTREE_ALIAS_PATTERN = re.compile(r"^(?P<label>.+?)\s*<(?P<target>[^>]+)>\s*$")


@dataclass(slots=True, frozen=True)
class Violation:
    """Represent one documentation consistency violation."""

    category: str
    detail: str


def _repo_root() -> Path:
    """Return the repository root."""
    return Path(__file__).resolve().parents[1]


def _scan_files(repo_root: Path) -> list[Path]:
    """Collect user-facing documentation files to scan."""
    files = [
        repo_root / "README.md",
        repo_root / "examples" / "README.md",
        repo_root / "examples" / "real_world" / "README.md",
    ]
    docs_root = repo_root / "docs"
    if docs_root.exists():
        files.extend(
            path
            for path in sorted(docs_root.rglob("*"))
            if path.is_file()
            and path.suffix in SCAN_FILE_SUFFIXES
            and "/_build/" not in path.as_posix()
        )
    return sorted(path for path in set(files) if path.exists())


def _extract_toctree_entries(index_path: Path) -> tuple[str, ...]:
    """Extract document entries from the first toctree in one index page."""
    entries: list[str] = []
    in_toctree = False
    for line in index_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped == ".. toctree::":
            in_toctree = True
            continue
        if not in_toctree:
            continue
        if not stripped or stripped.startswith(":"):
            continue
        if line.startswith("   "):
            alias_match = TOCTREE_ALIAS_PATTERN.match(stripped)
            entries.append(alias_match.group("target") if alias_match is not None else stripped)
            continue
        break
    return tuple(entries)


def _find_missing_docs_entries(repo_root: Path) -> list[Violation]:
    """Report missing toctree targets referenced by docs index pages."""
    violations: list[Violation] = []
    for index_path in (
        repo_root / "docs" / "index.rst",
        repo_root / "docs" / "examples" / "index.rst",
        repo_root / "docs" / "examples" / "core" / "index.rst",
        repo_root / "docs" / "examples" / "real_world" / "index.rst",
    ):
        if not index_path.exists():
            violations.append(
                Violation(
                    category="missing-index",
                    detail=f"{index_path.relative_to(repo_root)} is missing.",
                )
            )
            continue
        for entry in _extract_toctree_entries(index_path):
            if not (index_path.parent / f"{entry}.rst").exists():
                violations.append(
                    Violation(
                        category="missing-doc-entry",
                        detail=(
                            f"{index_path.relative_to(repo_root)} references missing document "
                            f"{(index_path.parent / f'{entry}.rst').relative_to(repo_root)}."
                        ),
                    )
                )
    return violations


def _parse_exports(repo_root: Path) -> set[str]:
    """Parse canonical top-level exports from ``src/mcpcraft/__init__.py``."""
    init_path = repo_root / "src" / "mcpcraft" / "__init__.py"
    tree = ast.parse(init_path.read_text(encoding="utf-8"), filename=str(init_path))
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if (
            isinstance(target, ast.Name)
            and target.id == "__all__"
            and isinstance(node.value, ast.List)
        ):
            exports = {
                item.value
                for item in node.value.elts
                if isinstance(item, ast.Constant) and isinstance(item.value, str)
            }
            return exports
    raise ValueError("Unable to locate __all__ in src/mcpcraft/__init__.py")


def _parse_api_rendered_symbols(repo_root: Path) -> set[str]:
    """Parse public symbols rendered explicitly in ``docs/api.rst``."""
    api_path = repo_root / "docs" / "api.rst"
    text = api_path.read_text(encoding="utf-8")
    return {match.group(1) for match in API_AUTODOC_DIRECTIVE_PATTERN.finditer(text)}


def _find_export_mismatch_violations(repo_root: Path) -> list[Violation]:
    """Find mismatches between curated exports and API documentation."""
    exports = _parse_exports(repo_root)
    rendered = _parse_api_rendered_symbols(repo_root)
    violations: list[Violation] = []
    missing = sorted(exports - rendered)
    if missing:
        violations.append(
            Violation(
                category="api-doc-missing-export",
                detail="docs/api.rst is missing rendered export coverage for: "
                + ", ".join(missing),
            )
        )
    extra = sorted(rendered - exports)
    if extra:
        violations.append(
            Violation(
                category="api-doc-extra-export",
                detail="docs/api.rst renders non-canonical exports: " + ", ".join(extra),
            )
        )
    return violations


def _find_missing_public_path_violations(repo_root: Path, files: list[Path]) -> list[Violation]:
    """Find local example links that point to missing files."""
    referenced_paths: set[str] = set()
    for path in files:
        text = path.read_text(encoding="utf-8")
        for match in PUBLIC_PATH_PATTERN.finditer(text):
            referenced_paths.add(match.group(1))
    return [
        Violation(
            category="missing-public-path",
            detail=f"Referenced public path does not exist: {path_str}",
        )
        for path_str in sorted(referenced_paths)
        if not (repo_root / path_str).exists()
    ]


def _find_internal_reference_violations(repo_root: Path, files: list[Path]) -> list[Violation]:
    """Find user-facing docs that reference internal package modules."""
    violations: list[Violation] = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(repo_root).as_posix()
        for match in INTERNAL_MODULE_PATTERN.finditer(text):
            violations.append(
                Violation(
                    category="internal-module-reference",
                    detail=f"{rel}: references internal module {match.group(0)!r}.",
                )
            )
    return violations


def _find_stale_name_violations(repo_root: Path, files: list[Path]) -> list[Violation]:
    """Find stale template-era package names in user-facing docs."""
    violations: list[Violation] = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(repo_root).as_posix()
        if STALE_NAME_PATTERN.search(text):
            violations.append(
                Violation(
                    category="stale-name",
                    detail=f"{rel}: found stale template-era package naming.",
                )
            )
    return violations


def validate_docs_tree() -> list[Violation]:
    """Collect documentation consistency violations."""
    repo_root = _repo_root()
    files = _scan_files(repo_root)
    violations: list[Violation] = []
    violations.extend(_find_missing_docs_entries(repo_root))
    violations.extend(_find_export_mismatch_violations(repo_root))
    violations.extend(_find_missing_public_path_violations(repo_root, files))
    violations.extend(_find_internal_reference_violations(repo_root, files))
    violations.extend(_find_stale_name_violations(repo_root, files))
    return violations


def main() -> int:
    """Run the documentation consistency checks."""
    violations = validate_docs_tree()
    if violations:
        for violation in violations:
            print(f"[{violation.category}] {violation.detail}")
        return 1
    print("Documentation checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

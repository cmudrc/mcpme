"""Check that Python modules, classes, and functions include docstrings."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TARGETS = ("src", "examples", "scripts")
SKIP_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    # Example and challenge scripts intentionally materialize runnable support
    # files under artifact directories. They are useful outputs, but they are
    # not part of the maintained checked-in source surface.
    "artifacts",
}
_LEGACY_SECTION_PATTERN = re.compile(r"(^|\n)(Args|Returns):\n")


@dataclass(frozen=True, slots=True)
class MissingDocstring:
    """Represent a missing docstring found during validation.

    :param path: The Python file containing the missing docstring.
    :param target: The module, class, or function name.
    :param kind: The AST node type.
    """

    path: Path
    target: str
    kind: str


@dataclass(frozen=True, slots=True)
class LegacyDocstringStyle:
    """Represent a maintained-source docstring that uses legacy sections.

    :param path: The Python file containing the legacy docstring.
    :param target: The module, class, or function name.
    :param kind: The AST node type.
    """

    path: Path
    target: str
    kind: str


def iter_python_files(targets: tuple[str, ...]) -> tuple[Path, ...]:
    """Collect Python files from the configured target directories.

    :param targets: Directory names to scan.
    :returns: All discovered Python files in sorted order.
    """
    files: list[Path] = []
    for target in targets:
        root = Path(target)
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            files.append(path)
    return tuple(sorted(files))


def _collect_from_body(
    path: Path,
    body: list[ast.stmt],
    parents: tuple[str, ...],
) -> tuple[list[MissingDocstring], list[LegacyDocstringStyle]]:
    """Collect missing docstrings from a list of AST statements.

    :param path: The source file path.
    :param body: Statements to inspect.
    :param parents: Parent names used to build qualified names.
    :returns: Any missing docstring records discovered in the body.
    """
    missing: list[MissingDocstring] = []
    legacy: list[LegacyDocstringStyle] = []
    for node in body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            qualified_name = ".".join((*parents, node.name))
            docstring = ast.get_docstring(node)
            if docstring is None:
                missing.append(
                    MissingDocstring(
                        path=path,
                        target=qualified_name,
                        kind=type(node).__name__,
                    )
                )
            elif _LEGACY_SECTION_PATTERN.search(docstring):
                legacy.append(
                    LegacyDocstringStyle(
                        path=path,
                        target=qualified_name,
                        kind=type(node).__name__,
                    )
                )
            child_missing, child_legacy = _collect_from_body(path, node.body, (*parents, node.name))
            missing.extend(child_missing)
            legacy.extend(child_legacy)
    return missing, legacy


def inspect_docstrings(path: Path) -> tuple[list[MissingDocstring], list[LegacyDocstringStyle]]:
    """Inspect one Python file for missing or legacy docstrings.

    :param path: The file to inspect.
    :returns: Missing docstring records and legacy-style docstring records.
    :raises SyntaxError: Raised if the file cannot be parsed.
    """
    module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    missing: list[MissingDocstring] = []
    legacy: list[LegacyDocstringStyle] = []
    module_docstring = ast.get_docstring(module)
    if module_docstring is None:
        missing.append(MissingDocstring(path=path, target="<module>", kind="Module"))
    elif _LEGACY_SECTION_PATTERN.search(module_docstring):
        legacy.append(LegacyDocstringStyle(path=path, target="<module>", kind="Module"))
    child_missing, child_legacy = _collect_from_body(path, module.body, ())
    missing.extend(child_missing)
    legacy.extend(child_legacy)
    return missing, legacy


def main() -> int:
    """Run the docstring validation script.

    :returns: Process exit code: ``0`` on success and ``1`` on failure.
    """
    missing: list[MissingDocstring] = []
    legacy: list[LegacyDocstringStyle] = []
    for path in iter_python_files(DEFAULT_TARGETS):
        file_missing, file_legacy = inspect_docstrings(path)
        missing.extend(file_missing)
        legacy.extend(file_legacy)

    if missing:
        for item in missing:
            print(f"{item.path}: missing docstring for {item.kind} {item.target}")
        return 1
    if legacy:
        for item in legacy:
            print(
                f"{item.path}: legacy docstring style for {item.kind} {item.target}; "
                "use Sphinx field lists instead of Args:/Returns:"
            )
        return 1
    print("Docstring checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

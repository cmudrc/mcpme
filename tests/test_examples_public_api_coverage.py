"""Keep the runnable examples aligned with the curated public API."""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES_ROOT = REPO_ROOT / "examples"
PACKAGE_INIT = REPO_ROOT / "src" / "mcpme" / "__init__.py"


def _public_symbols() -> tuple[str, ...]:
    """Parse the canonical export list from the package root."""
    module = ast.parse(PACKAGE_INIT.read_text(encoding="utf-8"), filename=str(PACKAGE_INIT))
    for node in module.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if (
            isinstance(target, ast.Name)
            and target.id == "__all__"
            and isinstance(node.value, ast.List)
        ):
            return tuple(
                item.value
                for item in node.value.elts
                if isinstance(item, ast.Constant) and isinstance(item.value, str)
            )
    raise AssertionError("Unable to locate __all__ in package __init__.py")


def _python_examples() -> tuple[Path, ...]:
    """Return the checked-in runnable example scripts."""
    return tuple(
        path
        for path in sorted(EXAMPLES_ROOT.rglob("*.py"))
        if "__pycache__" not in path.parts
        and "artifacts" not in path.parts
        and not path.name.startswith("_")
    )


def _collect_package_aliases(module: ast.Module) -> set[str]:
    """Collect local aliases used for ``import mcpme`` statements."""
    aliases: set[str] = set()
    for node in ast.walk(module):
        if not isinstance(node, ast.Import):
            continue
        for alias in node.names:
            if alias.name == "mcpme":
                aliases.add(alias.asname or "mcpme")
    return aliases


def _explicit_imported_symbols(module: ast.Module, exports: set[str]) -> set[str]:
    """Collect directly imported public symbols from example source."""
    covered: set[str] = set()
    for node in ast.walk(module):
        if not isinstance(node, ast.ImportFrom) or node.module != "mcpme":
            continue
        for alias in node.names:
            if alias.name == "*":
                covered.update(exports)
                continue
            if alias.name in exports:
                covered.add(alias.name)
    return covered


def _attribute_symbols(module: ast.Module, exports: set[str], aliases: set[str]) -> set[str]:
    """Collect public symbol usage through ``mcpme.<symbol>`` access."""
    covered: set[str] = set()
    for node in ast.walk(module):
        if not isinstance(node, ast.Attribute) or not isinstance(node.value, ast.Name):
            continue
        if node.value.id in aliases and node.attr in exports:
            covered.add(node.attr)
    return covered


def test_examples_cover_all_curated_public_symbols() -> None:
    """Every curated public export should appear in at least one runnable example."""
    symbols = _public_symbols()
    export_set = set(symbols)
    covered: set[str] = set()
    symbol_to_examples: dict[str, list[str]] = {symbol: [] for symbol in symbols}

    for path in _python_examples():
        module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        aliases = _collect_package_aliases(module)
        used = _explicit_imported_symbols(module, export_set) | _attribute_symbols(
            module,
            export_set,
            aliases,
        )
        relative = path.relative_to(REPO_ROOT).as_posix()
        for symbol in sorted(used):
            covered.add(symbol)
            symbol_to_examples[symbol].append(relative)

    missing = sorted(export_set - covered)
    assert not missing, (
        "Runnable examples must cover every curated public symbol. Missing: "
        + ", ".join(missing)
        + f".\nSymbol usage map: {symbol_to_examples}"
    )

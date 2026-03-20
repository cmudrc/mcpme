#!/usr/bin/env python3
"""Generate Sphinx example pages from canonical example module docstrings."""

from __future__ import annotations

import argparse
import ast
import re
from dataclasses import dataclass
from pathlib import Path

CORE_REQUIRED_SECTIONS = (
    "Introduction",
    "Preset Environment",
    "Technical Implementation",
    "Expected Results",
    "References",
)
REAL_WORLD_REQUIRED_SECTIONS = (
    "Introduction",
    "Preset Environment",
    "Technical Implementation",
    "Expected Results",
    "Availability",
    "References",
)
HEADING_CHARS = {
    "Introduction": "-",
    "Preset Environment": "-",
    "Technical Implementation": "-",
    "Expected Results": "-",
    "Availability": "-",
    "References": "-",
    "Source Code": "-",
    "Ingest Script": "~",
    "Serve Script": "~",
    "Use Script": "~",
}


@dataclass(slots=True, frozen=True)
class CoreExampleDocSpec:
    """Represent one core example and its parsed canonical docs content."""

    rel_path: str
    slug: str
    title: str
    source_start_line: int
    sections: dict[str, str]


@dataclass(slots=True, frozen=True)
class RealWorldExampleDocSpec:
    """Represent one real-world example and its parsed canonical docs content."""

    case_dir_rel_path: str
    slug: str
    title: str
    ingest_rel_path: str
    ingest_source_start_line: int
    serve_rel_path: str
    serve_source_start_line: int
    use_rel_path: str
    use_source_start_line: int
    sections: dict[str, str]


def _repo_root() -> Path:
    """Return the repository root path."""
    return Path(__file__).resolve().parents[1]


def _discover_core_examples(repo_root: Path) -> list[Path]:
    """Discover runnable core example scripts."""
    examples_root = repo_root / "examples" / "core"
    return [path for path in sorted(examples_root.glob("*.py")) if not path.name.startswith("_")]


def _discover_real_world_examples(repo_root: Path) -> list[Path]:
    """Discover runnable real-world example directories."""
    examples_root = repo_root / "examples" / "real_world"
    if not examples_root.exists():
        return []
    case_dirs: list[Path] = []
    for path in sorted(examples_root.iterdir()):
        if path.name.startswith("_") or not path.is_dir():
            continue
        if (
            (path / "ingest.py").exists()
            and (path / "serve.py").exists()
            and (path / "use.py").exists()
        ):
            case_dirs.append(path)
    return case_dirs


def _parse_module_doc_text(path: Path) -> tuple[str, int]:
    """Parse module docstring text and source start line from one script."""
    source = path.read_text(encoding="utf-8")
    module = ast.parse(source, filename=str(path))
    docstring = ast.get_docstring(module, clean=False)
    if not isinstance(docstring, str) or not docstring.strip():
        raise ValueError(f"{path}: missing module docstring.")
    source_start_line = 1
    if module.body:
        first = module.body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
            and isinstance(first.end_lineno, int)
        ):
            source_start_line = first.end_lineno + 1
    lines = source.splitlines()
    while source_start_line <= len(lines) and not lines[source_start_line - 1].strip():
        source_start_line += 1
    return docstring, source_start_line


def _parse_sections(
    *,
    doc_text: str,
    required_sections: tuple[str, ...],
    source_path: Path,
) -> dict[str, str]:
    """Parse canonical ``##`` sections from one example docstring."""
    heading_pattern = re.compile(r"^##\s+(.+?)\s*$")
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for raw_line in doc_text.splitlines():
        line = raw_line.rstrip()
        match = heading_pattern.match(line.strip())
        if match is not None:
            heading = match.group(1).strip()
            current = heading if heading in required_sections else None
            if current is not None:
                sections[current] = []
            continue
        if current is not None:
            sections[current].append(line)
    missing = [section for section in required_sections if section not in sections]
    if missing:
        raise ValueError(f"{source_path}: missing canonical section(s): {missing}")
    return {heading: "\n".join(body).strip() for heading, body in sections.items()}


def _title_from_path(path: Path) -> str:
    """Build a human-readable title from one source path."""
    return path.stem.replace("_", " ").title()


def _title_from_dir(path: Path) -> str:
    """Build a human-readable title from one example directory name."""
    return path.name.replace("_", " ").title()


def _build_core_specs(repo_root: Path) -> list[CoreExampleDocSpec]:
    """Parse all core example docstrings into documentation specs."""
    specs: list[CoreExampleDocSpec] = []
    for path in _discover_core_examples(repo_root):
        doc_text, source_start_line = _parse_module_doc_text(path)
        specs.append(
            CoreExampleDocSpec(
                rel_path=path.relative_to(repo_root).as_posix(),
                slug=path.stem,
                title=_title_from_path(path),
                source_start_line=source_start_line,
                sections=_parse_sections(
                    doc_text=doc_text,
                    required_sections=CORE_REQUIRED_SECTIONS,
                    source_path=path,
                ),
            )
        )
    return specs


def _build_real_world_specs(repo_root: Path) -> list[RealWorldExampleDocSpec]:
    """Parse all real-world example docstrings into documentation specs."""
    specs: list[RealWorldExampleDocSpec] = []
    for case_dir in _discover_real_world_examples(repo_root):
        ingest_path = case_dir / "ingest.py"
        serve_path = case_dir / "serve.py"
        use_path = case_dir / "use.py"
        use_doc_text, use_source_start_line = _parse_module_doc_text(use_path)
        _, ingest_source_start_line = _parse_module_doc_text(ingest_path)
        _, serve_source_start_line = _parse_module_doc_text(serve_path)
        specs.append(
            RealWorldExampleDocSpec(
                case_dir_rel_path=case_dir.relative_to(repo_root).as_posix(),
                slug=case_dir.name,
                title=_title_from_dir(case_dir),
                ingest_rel_path=ingest_path.relative_to(repo_root).as_posix(),
                ingest_source_start_line=ingest_source_start_line,
                serve_rel_path=serve_path.relative_to(repo_root).as_posix(),
                serve_source_start_line=serve_source_start_line,
                use_rel_path=use_path.relative_to(repo_root).as_posix(),
                use_source_start_line=use_source_start_line,
                sections=_parse_sections(
                    doc_text=use_doc_text,
                    required_sections=REAL_WORLD_REQUIRED_SECTIONS,
                    source_path=use_path,
                ),
            )
        )
    return specs


def _heading(title: str, char: str = "=") -> str:
    """Render one reStructuredText heading."""
    return f"{title}\n{char * len(title)}"


def _render_core_page(spec: CoreExampleDocSpec) -> str:
    """Render one generated core example documentation page."""
    parts = [
        ".. This file is generated by scripts/generate_example_docs.py.",
        "",
        _heading(spec.title),
        "",
        f"Source: ``{spec.rel_path}``",
        "",
    ]
    for section in CORE_REQUIRED_SECTIONS:
        parts.extend(
            [
                _heading(section, HEADING_CHARS[section]),
                "",
                spec.sections[section],
                "",
            ]
        )
    parts.extend(
        [
            _heading("Source Code", HEADING_CHARS["Source Code"]),
            "",
            f".. literalinclude:: ../../../{spec.rel_path}",
            "   :language: python",
            "   :linenos:",
            f"   :lines: {spec.source_start_line}-",
            "",
        ]
    )
    return "\n".join(parts).rstrip() + "\n"


def _render_real_world_page(spec: RealWorldExampleDocSpec) -> str:
    """Render one generated real-world example documentation page."""
    parts = [
        ".. This file is generated by scripts/generate_example_docs.py.",
        "",
        _heading(spec.title),
        "",
        (
            f"Source: ``{spec.use_rel_path}`` with companions "
            f"``{spec.ingest_rel_path}`` and ``{spec.serve_rel_path}``"
        ),
        "",
    ]
    for section in REAL_WORLD_REQUIRED_SECTIONS:
        parts.extend(
            [
                _heading(section, HEADING_CHARS[section]),
                "",
                spec.sections[section],
                "",
            ]
        )
    parts.extend(
        [
            _heading("Source Code", HEADING_CHARS["Source Code"]),
            "",
            _heading("Ingest Script", HEADING_CHARS["Ingest Script"]),
            "",
            f".. literalinclude:: ../../../{spec.ingest_rel_path}",
            "   :language: python",
            "   :linenos:",
            f"   :lines: {spec.ingest_source_start_line}-",
            "",
            _heading("Serve Script", HEADING_CHARS["Serve Script"]),
            "",
            f".. literalinclude:: ../../../{spec.serve_rel_path}",
            "   :language: python",
            "   :linenos:",
            f"   :lines: {spec.serve_source_start_line}-",
            "",
            _heading("Use Script", HEADING_CHARS["Use Script"]),
            "",
            f".. literalinclude:: ../../../{spec.use_rel_path}",
            "   :language: python",
            "   :linenos:",
            f"   :lines: {spec.use_source_start_line}-",
            "",
        ]
    )
    return "\n".join(parts).rstrip() + "\n"


def _render_examples_index(
    core_specs: list[CoreExampleDocSpec],
    real_world_specs: list[RealWorldExampleDocSpec],
) -> str:
    """Render the top-level generated examples index page."""
    lines = [
        ".. This file is generated by scripts/generate_example_docs.py.",
        "",
        _heading("Examples"),
        "",
        "The examples documentation is split into two maintained lanes:",
        "",
        "- ``examples/core`` for the curated public-API teaching contract.",
        "- ``examples/real_world`` for richer optional upstream walkthroughs.",
        "",
        "Both lanes keep checked-in support inputs under ``examples/support`` and",
        "write only derived outputs under ``artifacts/examples``.",
        "",
        ".. toctree::",
        "   :maxdepth: 1",
        "",
        "   core/index",
        "   real_world/index",
        "",
        "Lane Inventory",
        "--------------",
        "",
        f"- ``examples/core``: {len(core_specs)} runnable teaching example(s).",
        f"- ``examples/real_world``: {len(real_world_specs)} richer optional walkthrough(s).",
        "",
    ]
    return "\n".join(lines)


def _render_core_index(specs: list[CoreExampleDocSpec]) -> str:
    """Render the generated core examples index page."""
    lines = [
        ".. This file is generated by scripts/generate_example_docs.py.",
        "",
        _heading("Core Examples"),
        "",
        "The core examples are part of the maintained public contract for",
        "`mcpcraft`. Each page below is generated from the example module",
        "docstring and the checked-in source file, so the code and prose stay",
        "aligned. Core examples that need helper inputs keep them under",
        "``examples/support/<example_id>/``, while derived outputs stay under",
        "``artifacts/examples/core/<example_id>/``.",
        "",
        ".. toctree::",
        "   :maxdepth: 1",
        "",
    ]
    lines.extend(f"   {spec.slug}" for spec in specs)
    lines.extend(
        [
            "",
            "Example Inventory",
            "-----------------",
            "",
        ]
    )
    for spec in specs:
        first_line = spec.sections["Introduction"].splitlines()[0].strip()
        lines.append(f"- ``{spec.rel_path}``: {first_line}")
    lines.append("")
    return "\n".join(lines)


def _render_real_world_index(specs: list[RealWorldExampleDocSpec]) -> str:
    """Render the generated real-world examples index page."""
    lines = [
        ".. This file is generated by scripts/generate_example_docs.py.",
        "",
        _heading("Real-World Examples"),
        "",
        "The real-world examples are the richer optional lane under",
        "``examples/``. They document heavier upstream workflows while still",
        "using only the public `mcpcraft` surface and a stable",
        "``passed``/``skipped_unavailable`` JSON shape. Each walkthrough is",
        "split into ``ingest.py``, ``serve.py``, and ``use.py`` so the generated",
        "facade can be inspected after ingestion, served over stdio MCP, and",
        "then exercised through a client request. Checked-in support inputs live",
        "under ``examples/support/real_world/``, while generated facades and run",
        "artifacts stay under ``artifacts/examples/real_world/``.",
        "",
        ".. toctree::",
        "   :maxdepth: 1",
        "",
    ]
    lines.extend(f"   {spec.slug}" for spec in specs)
    lines.extend(
        [
            "",
            "Example Inventory",
            "-----------------",
            "",
        ]
    )
    for spec in specs:
        first_line = spec.sections["Introduction"].splitlines()[0].strip()
        lines.append(f"- ``{spec.case_dir_rel_path}``: {first_line}")
    lines.append("")
    return "\n".join(lines)


def _write_if_changed(path: Path, content: str) -> bool:
    """Write one file only when the rendered content changed."""
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def _expected_outputs(
    repo_root: Path,
    core_specs: list[CoreExampleDocSpec],
    real_world_specs: list[RealWorldExampleDocSpec],
) -> dict[Path, str]:
    """Return the generated docs paths and their expected contents."""
    docs_root = repo_root / "docs" / "examples"
    outputs: dict[Path, str] = {
        docs_root / "index.rst": _render_examples_index(core_specs, real_world_specs),
        docs_root / "core" / "index.rst": _render_core_index(core_specs),
        docs_root / "real_world" / "index.rst": _render_real_world_index(real_world_specs),
    }
    for spec in core_specs:
        outputs[docs_root / "core" / f"{spec.slug}.rst"] = _render_core_page(spec)
    for spec in real_world_specs:
        outputs[docs_root / "real_world" / f"{spec.slug}.rst"] = _render_real_world_page(spec)
    return outputs


def _generated_docs_root(outputs: dict[Path, str]) -> Path:
    """Return the root directory that holds generated example docs."""
    return next(iter(outputs)).parent


def _check(outputs: dict[Path, str]) -> int:
    """Check that generated example docs are up to date."""
    mismatches = [
        path
        for path, content in outputs.items()
        if not path.exists() or path.read_text(encoding="utf-8") != content
    ]
    docs_root = _generated_docs_root(outputs)
    existing_generated = {path for path in docs_root.rglob("*.rst")}
    extras = sorted(existing_generated - set(outputs))
    if mismatches or extras:
        for path in mismatches:
            print(f"Out-of-date generated example docs: {path}")
        for path in extras:
            print(f"Unexpected generated example docs file: {path}")
        return 1
    print("Generated example docs are up to date.")
    return 0


def _write(outputs: dict[Path, str]) -> int:
    """Write the generated example docs to disk."""
    changed = 0
    docs_root = _generated_docs_root(outputs)
    docs_root.mkdir(parents=True, exist_ok=True)
    expected_paths = set(outputs)
    for existing in sorted(docs_root.rglob("*.rst")):
        if existing not in expected_paths:
            existing.unlink()
            changed += 1
    for path, content in outputs.items():
        changed += int(_write_if_changed(path, content))
    for existing_dir in sorted(docs_root.rglob("*"), reverse=True):
        if existing_dir.is_dir() and not any(existing_dir.iterdir()):
            existing_dir.rmdir()
    print(f"Generated example docs updated ({changed} file(s) changed).")
    return 0


def main() -> int:
    """Generate or check example documentation pages."""
    parser = argparse.ArgumentParser(description="Generate Sphinx pages for runnable examples.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify that generated docs are current.",
    )
    args = parser.parse_args()

    repo_root = _repo_root()
    core_specs = _build_core_specs(repo_root)
    real_world_specs = _build_real_world_specs(repo_root)
    outputs = _expected_outputs(repo_root, core_specs, real_world_specs)
    return _check(outputs) if args.check else _write(outputs)


if __name__ == "__main__":
    raise SystemExit(main())

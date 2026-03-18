#!/usr/bin/env python3
"""Generate Sphinx case-study pages from canonical case-study docstrings."""

from __future__ import annotations

import argparse
import ast
import re
from dataclasses import dataclass
from pathlib import Path

REQUIRED_SECTIONS = (
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
class CaseStudyDocSpec:
    """Represent one case study and its parsed canonical docs content."""

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


def _discover_case_studies(repo_root: Path) -> list[Path]:
    """Discover runnable case-study directories with ingest/use entrypoints."""
    case_studies_root = repo_root / "case_studies"
    case_dirs: list[Path] = []
    for path in sorted(case_studies_root.iterdir()):
        if path.name.startswith("_") or path.name == "support" or not path.is_dir():
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


def _parse_sections(*, doc_text: str, source_path: Path) -> dict[str, str]:
    """Parse canonical ``##`` sections from one case-study docstring."""
    heading_pattern = re.compile(r"^##\s+(.+?)\s*$")
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for raw_line in doc_text.splitlines():
        line = raw_line.rstrip()
        match = heading_pattern.match(line.strip())
        if match is not None:
            heading = match.group(1).strip()
            current = heading if heading in REQUIRED_SECTIONS else None
            if current is not None:
                sections[current] = []
            continue
        if current is not None:
            sections[current].append(line)
    missing = [section for section in REQUIRED_SECTIONS if section not in sections]
    if missing:
        raise ValueError(f"{source_path}: missing canonical section(s): {missing}")
    return {heading: "\n".join(body).strip() for heading, body in sections.items()}


def _slug_for_case_study(case_dir: Path) -> str:
    """Build a deterministic slug from one case-study directory."""
    return case_dir.name


def _title_for_case_study(case_dir: Path) -> str:
    """Build a human-readable title from one case-study directory name."""
    return case_dir.name.replace("_", " ").title()


def _build_case_study_specs(repo_root: Path) -> list[CaseStudyDocSpec]:
    """Parse all case-study docstrings into documentation specs."""
    specs: list[CaseStudyDocSpec] = []
    for case_dir in _discover_case_studies(repo_root):
        ingest_path = case_dir / "ingest.py"
        serve_path = case_dir / "serve.py"
        use_path = case_dir / "use.py"
        use_doc_text, use_source_start_line = _parse_module_doc_text(use_path)
        _, ingest_source_start_line = _parse_module_doc_text(ingest_path)
        _, serve_source_start_line = _parse_module_doc_text(serve_path)
        specs.append(
            CaseStudyDocSpec(
                case_dir_rel_path=case_dir.relative_to(repo_root).as_posix(),
                slug=_slug_for_case_study(case_dir),
                title=_title_for_case_study(case_dir),
                ingest_rel_path=ingest_path.relative_to(repo_root).as_posix(),
                ingest_source_start_line=ingest_source_start_line,
                serve_rel_path=serve_path.relative_to(repo_root).as_posix(),
                serve_source_start_line=serve_source_start_line,
                use_rel_path=use_path.relative_to(repo_root).as_posix(),
                use_source_start_line=use_source_start_line,
                sections=_parse_sections(doc_text=use_doc_text, source_path=use_path),
            )
        )
    return specs


def _heading(title: str, char: str = "=") -> str:
    """Render one reStructuredText heading."""
    return f"{title}\n{char * len(title)}"


def _render_case_study_page(spec: CaseStudyDocSpec) -> str:
    """Render one generated case-study documentation page."""
    parts = [
        ".. This file is generated by scripts/generate_case_study_docs.py.",
        "",
        _heading(spec.title),
        "",
        (
            f"Source: ``{spec.use_rel_path}`` with companions "
            f"``{spec.ingest_rel_path}`` and ``{spec.serve_rel_path}``"
        ),
        "",
    ]
    for section in REQUIRED_SECTIONS:
        body = spec.sections[section]
        parts.extend(
            [
                _heading(section, HEADING_CHARS[section]),
                "",
                body,
                "",
            ]
        )
    parts.extend(
        [
            _heading("Source Code", HEADING_CHARS["Source Code"]),
            "",
            _heading("Ingest Script", HEADING_CHARS["Ingest Script"]),
            "",
            f".. literalinclude:: ../../{spec.ingest_rel_path}",
            "   :language: python",
            "   :linenos:",
            f"   :lines: {spec.ingest_source_start_line}-",
            "",
            _heading("Serve Script", HEADING_CHARS["Serve Script"]),
            "",
            f".. literalinclude:: ../../{spec.serve_rel_path}",
            "   :language: python",
            "   :linenos:",
            f"   :lines: {spec.serve_source_start_line}-",
            "",
            _heading("Use Script", HEADING_CHARS["Use Script"]),
            "",
            f".. literalinclude:: ../../{spec.use_rel_path}",
            "   :language: python",
            "   :linenos:",
            f"   :lines: {spec.use_source_start_line}-",
            "",
        ]
    )
    return "\n".join(parts).rstrip() + "\n"


def _render_case_studies_index(specs: list[CaseStudyDocSpec]) -> str:
    """Render the generated case-studies index page."""
    lines = [
        ".. This file is generated by scripts/generate_case_study_docs.py.",
        "",
        _heading("Case Studies"),
        "",
        "The case studies are a separate lane from the small core examples.",
        "They document richer real-upstream workflows while preserving the",
        "public-API-only contract and a stable `passed`/`skipped_unavailable`",
        "JSON output shape. Each case is split into `ingest.py`, `serve.py`,",
        "and `use.py` so the generated facade can be inspected after ingestion,",
        "served over stdio MCP, and exercised through MCP requests without",
        "regenerating it.",
        "Checked-in support inputs live under",
        "`case_studies/support/`, while generated facades and run artifacts",
        "stay under `artifacts/case_studies/`.",
        "",
        ".. toctree::",
        "   :maxdepth: 1",
        "",
    ]
    lines.extend(f"   {spec.slug}" for spec in specs)
    lines.extend(
        [
            "",
            "Case Study Inventory",
            "--------------------",
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


def _expected_outputs(repo_root: Path, specs: list[CaseStudyDocSpec]) -> dict[Path, str]:
    """Return the generated docs paths and their expected contents."""
    docs_root = repo_root / "docs" / "case_studies"
    outputs = {docs_root / "index.rst": _render_case_studies_index(specs)}
    for spec in specs:
        outputs[docs_root / f"{spec.slug}.rst"] = _render_case_study_page(spec)
    return outputs


def _check(outputs: dict[Path, str]) -> int:
    """Check that generated case-study docs are up to date."""
    mismatches = [
        path
        for path, content in outputs.items()
        if not path.exists() or path.read_text(encoding="utf-8") != content
    ]
    existing_generated = {
        path
        for path in (next(iter(outputs)).parent).glob("*.rst")
        if path.name != "index.rst" or path in outputs
    }
    extras = sorted(existing_generated - set(outputs))
    if mismatches or extras:
        for path in mismatches:
            print(f"Out-of-date generated case-study docs: {path}")
        for path in extras:
            print(f"Unexpected generated case-study docs file: {path}")
        return 1
    print("Generated case-study docs are up to date.")
    return 0


def _write(outputs: dict[Path, str]) -> int:
    """Write the generated case-study docs to disk."""
    changed = 0
    docs_root = next(iter(outputs)).parent
    docs_root.mkdir(parents=True, exist_ok=True)
    expected_paths = set(outputs)
    for existing in docs_root.glob("*.rst"):
        if existing not in expected_paths:
            existing.unlink()
            changed += 1
    for path, content in outputs.items():
        changed += int(_write_if_changed(path, content))
    print(f"Generated case-study docs updated ({changed} file(s) changed).")
    return 0


def main() -> int:
    """Generate or check case-study documentation pages."""
    parser = argparse.ArgumentParser(description="Generate Sphinx pages for case studies.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify that generated docs are current.",
    )
    args = parser.parse_args()

    repo_root = _repo_root()
    specs = _build_case_study_specs(repo_root)
    outputs = _expected_outputs(repo_root, specs)
    return _check(outputs) if args.check else _write(outputs)


if __name__ == "__main__":
    raise SystemExit(main())

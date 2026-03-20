#!/usr/bin/env python3
"""Generate self-contained README files for the live challenge track.

The challenge suite is intentionally separate from the public example contract,
but each case should still be understandable on its own. This script renders
checked-in README files directly from the canonical ``challenge.toml`` files so
the prose, fixtures, and runnable catalog entries stay aligned.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mcpcraft._challenges import ChallengeSpec, ChallengeWorkflowStep, load_challenge_catalog


def _repo_root() -> Path:
    """Return the repository root path."""
    return Path(__file__).resolve().parents[1]


def _catalog_root(repo_root: Path) -> Path:
    """Return the checked-in challenge case root."""
    return repo_root / "challenges" / "cases"


def _heading(title: str, level: int = 1) -> str:
    """Render one Markdown heading."""
    return f"{'#' * level} {title}"


def _format_target_value(value: str | tuple[str, ...]) -> str:
    """Format one target value for Markdown prose."""
    if isinstance(value, str):
        return f"`{value}`"
    return " ".join(f"`{token}`" for token in value)


def _render_fixture_list(spec: ChallengeSpec, repo_root: Path) -> list[str]:
    """Render fixture bullets for one challenge case.

    Keeping the fixture listing explicit makes each challenge read like a real
    example directory instead of a magical test case with hidden inputs.
    """
    fixture_dir = spec.case_dir / "fixtures"
    if not fixture_dir.exists():
        return ["This case does not need checked-in fixtures."]
    bullets: list[str] = []
    for path in sorted(path for path in fixture_dir.rglob("*") if path.is_file()):
        relative = path.relative_to(repo_root)
        bullets.append(f"`{relative.as_posix()}`")
    return bullets


def _render_step(step: ChallengeWorkflowStep, index: int) -> str:
    """Render one workflow step as readable Markdown.

    The generated case README should read like a worked example, so we render
    each workflow step as a short labeled section instead of a dense serialized
    blob.
    """
    label = step.label or step.tool
    lines = [f"### {index}. {label}", "", f"Tool: `{step.tool}`"]
    if step.arguments:
        lines.append("")
        lines.append("Arguments:")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(step.arguments, indent=2, sort_keys=True))
        lines.append("```")
    expectations: list[str] = []
    if step.expect_text_contains:
        expectations.append(f"text contains {list(step.expect_text_contains)!r}")
    if step.expect_json_fields:
        expectations.append(f"json fields {step.expect_json_fields!r}")
    if step.expect_structured_fields:
        expectations.append(f"structured fields {step.expect_structured_fields!r}")
    if step.expect_files_exist:
        expectations.append(f"files exist {list(step.expect_files_exist)!r}")
    if step.expect_files_nonempty:
        expectations.append(f"files are non-empty {list(step.expect_files_nonempty)!r}")
    if step.expect_files_missing:
        expectations.append(f"files are missing {list(step.expect_files_missing)!r}")
    if expectations:
        lines.append("")
        lines.append(f"Expectations: {'; '.join(expectations)}.")
    if step.capture_json:
        lines.append("")
        lines.append(f"Captures: `{step.capture_json}`")
    return "\n".join(lines)


def _render_ingestion_breadth(spec: ChallengeSpec) -> list[str]:
    """Render one challenge's scaffold breadth expectations for Markdown."""
    if spec.ingestion.min_generated_tools == 0 and not spec.ingestion.required_tools:
        return ["This case relies on its workflow without extra breadth assertions."]
    lines: list[str] = []
    if spec.ingestion.min_generated_tools:
        lines.append(f"- Minimum generated tools: `{spec.ingestion.min_generated_tools}`")
    if spec.ingestion.required_tools:
        required = ", ".join(f"`{tool}`" for tool in spec.ingestion.required_tools)
        lines.append(f"- Required generated tools: {required}")
    return lines


def _render_setup_files(spec: ChallengeSpec, repo_root: Path) -> list[str]:
    """Render any prepared workflow inputs for one challenge."""
    if not spec.rendered_files:
        return ["This case does not need rendered setup inputs."]
    lines: list[str] = []
    for rendered_file in spec.rendered_files:
        source = Path(rendered_file.source)
        if not source.is_absolute():
            source = spec.case_dir / source
        try:
            source_label = source.relative_to(repo_root).as_posix()
        except ValueError:
            source_label = str(source)
        lines.append(
            f"- Render `{source_label}` to `{rendered_file.destination}` before the workflow runs."
        )
    return lines


def _render_case_readme(spec: ChallengeSpec, repo_root: Path) -> str:
    """Render one challenge-local README file."""
    relative_catalog = spec.catalog_path.relative_to(repo_root).as_posix()
    fixture_lines = _render_fixture_list(spec, repo_root)
    run_command = f"make challenge CASE={spec.id}"
    raw_command = (
        "PYTHONPATH=src .venv/bin/python scripts/run_challenges.py "
        f"--catalog-dir challenges/cases --tier all --only {spec.id}"
    )
    parts = [
        "<!-- This file is generated by scripts/generate_challenge_docs.py. -->",
        "",
        _heading(spec.title),
        "",
        spec.example.summary,
        "",
        _heading("Why This Case Exists", 2),
        "",
        spec.example.motivation,
        "",
        _heading("Case Shape", 2),
        "",
        f"- ID: `{spec.id}`",
        f"- Family: `{spec.family}`",
        f"- Difficulty: `{spec.difficulty}`",
        f"- Tier: `{spec.tier}`",
        f"- Style: `{spec.style}`",
        f"- Workflow Slice: `{spec.slice}`",
        f"- Target Kind: `{spec.target.kind}`",
        f"- Upstream Target: {_format_target_value(spec.target.value)}",
        f"- Catalog Source: `{relative_catalog}`",
        "",
        _heading("Ingestion Breadth", 2),
        "",
    ]
    parts.extend(_render_ingestion_breadth(spec))
    parts.extend(
        [
            "",
            _heading("Why This Stays A Challenge", 2),
            "",
            "This case keeps its ingestion recipe and workflow assertions in",
            "`challenge.toml` instead of checking in companion `ingest.py` and",
            "`use.py` scripts. That boundary is intentional: the challenge lane",
            "should stay a compact problem statement rather than turning into a",
            "worked answer key like the real-world example lane.",
            "",
            _heading("Run This Case", 2),
            "",
            "Use the convenience target:",
            "",
            "```bash",
            run_command,
            "```",
            "",
            "Or call the runner directly:",
            "",
            "```bash",
            raw_command,
            "```",
            "",
            _heading("Prepared Inputs", 2),
            "",
        ]
    )
    parts.extend(_render_setup_files(spec, repo_root))
    parts.extend(
        [
            "",
            _heading("Fixtures", 2),
            "",
        ]
    )
    parts.extend(
        f"- {line}" if not line.startswith("This case") else line for line in fixture_lines
    )
    parts.extend(
        [
            "",
            _heading("Workflow", 2),
            "",
        ]
    )
    for index, step in enumerate(spec.workflow_steps, start=1):
        parts.extend([_render_step(step, index), ""])
    parts.extend(
        [
            _heading("What This Case Proves", 2),
            "",
        ]
    )
    parts.extend(f"- {item}" for item in spec.example.proves)
    if spec.example.limitations:
        parts.extend(
            [
                "",
                _heading("Known Limits", 2),
                "",
            ]
        )
        parts.extend(f"- {item}" for item in spec.example.limitations)
    if spec.notes:
        parts.extend(
            [
                "",
                _heading("Notes", 2),
                "",
                spec.notes,
            ]
        )
    parts.extend(
        [
            "",
            _heading("Challenge Definition", 2),
            "",
            "```toml",
            spec.catalog_path.read_text(encoding="utf-8").rstrip(),
            "```",
            "",
        ]
    )
    return "\n".join(parts)


def _render_family_ladders(specs: tuple[ChallengeSpec, ...], repo_root: Path) -> list[str]:
    """Render one family-by-difficulty matrix for the challenge catalog."""
    del repo_root
    families = sorted({spec.family for spec in specs})
    index: dict[tuple[str, str], list[ChallengeSpec]] = {}
    for spec in specs:
        index.setdefault((spec.family, spec.difficulty), []).append(spec)
    lines = [
        "| Family | easy | medium | hard | insane |",
        "| --- | --- | --- | --- | --- |",
    ]
    for family in families:
        cells = [f"`{family}`"]
        for difficulty in ("easy", "medium", "hard", "insane"):
            matched = sorted(index.get((family, difficulty), ()), key=lambda spec: spec.id)
            if not matched:
                cells.append("-")
                continue
            links = ", ".join(f"[`{spec.id}`](cases/{spec.id}/README.md)" for spec in matched)
            cells.append(links)
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def _render_challenge_index(specs: tuple[ChallengeSpec, ...], repo_root: Path) -> str:
    """Render the top-level challenge README overview."""
    lines = [
        "<!-- This file is generated by scripts/generate_challenge_docs.py. -->",
        "",
        _heading("Live Raw-Upstream Challenges"),
        "",
        "This directory holds the live, non-gating raw-upstream challenge track for `mcpcraft`.",
        "Each case lives in its own folder with a canonical `challenge.toml`, any tiny",
        "checked-in fixtures it needs, and a generated `README.md` that explains why the",
        "case exists and how to run it in isolation.",
        "",
        _heading("Why These Cases Matter", 2),
        "",
        "- They pressure-test one-shot ingestion against real engineering packages and CLIs.",
        "- Many cases assert scaffold breadth explicitly so the suite checks more than one route.",
        (
            "- They stay separate from the public example contract so we can keep them "
            "brutally honest."
        ),
        (
            "- Unlike the real-world examples, they intentionally keep ingestion and workflow "
            "compressed into `challenge.toml` so contributors still have to solve the "
            "wrapping problem themselves."
        ),
        "- They are still documented enough to serve as worked examples for contributors.",
        "",
        _heading("Run The Suite", 2),
        "",
        "```bash",
        "make challenge-deps",
        "make challenges-subset",
        "make challenges-full",
        "make challenge CASE=openmdao_file_utils",
        "PYTHONPATH=src .venv/bin/python scripts/run_challenges.py --tier all --family avl",
        "```",
        "",
        _heading("Install Optional Runtimes", 2),
        "",
        "The broader challenge lane expects its extra CLI tools under the repo-local",
        "`.challenge-tools/` prefix. The `challenge`, `challenges-subset`,",
        "`challenges-full`, and `run-real-world-examples` targets prepend",
        "`.challenge-tools/bin` to `PATH` automatically.",
        "",
        "```bash",
        "make challenge-deps",
        "make challenge-deps PROFILE=subset",
        "```",
        "",
        _heading("Family Ladders", 2),
        "",
    ]
    lines.extend(_render_family_ladders(specs, repo_root))
    lines.extend(
        [
            "",
            _heading("Case Inventory", 2),
            "",
            "| Case | Family | Difficulty | Tier | Slice | Target | Summary |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for spec in specs:
        case_readme = spec.case_dir / "README.md"
        case_link = case_readme.relative_to(repo_root / "challenges").as_posix()
        lines.append(
            "| "
            f"[`{spec.id}`]({case_link}) | "
            f"`{spec.family}` | "
            f"`{spec.difficulty}` | "
            f"`{spec.tier}` | "
            f"`{spec.slice}` | "
            f"{_format_target_value(spec.target.value)} | "
            f"{spec.example.summary} |"
        )
    lines.append("")
    return "\n".join(lines)


def _expected_outputs(repo_root: Path, specs: tuple[ChallengeSpec, ...]) -> dict[Path, str]:
    """Return generated README paths and expected contents."""
    outputs = {repo_root / "challenges" / "README.md": _render_challenge_index(specs, repo_root)}
    for spec in specs:
        outputs[spec.case_dir / "README.md"] = _render_case_readme(spec, repo_root)
    return outputs


def _write_if_changed(path: Path, content: str) -> bool:
    """Write one generated file only when contents changed."""
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def _check(outputs: dict[Path, str]) -> int:
    """Check that generated challenge docs are up to date."""
    mismatches = [
        path
        for path, content in outputs.items()
        if not path.exists() or path.read_text(encoding="utf-8") != content
    ]
    generated_case_readmes = {
        path
        for path in (next(iter(outputs)).parent / "cases").glob("*/README.md")
        if path.is_file()
    }
    expected_case_readmes = {
        path for path in outputs if path.name == "README.md" and "cases" in path.parts
    }
    extras = sorted(generated_case_readmes - expected_case_readmes)
    if mismatches or extras:
        for path in mismatches:
            print(f"Out-of-date generated challenge docs: {path}")
        for path in extras:
            print(f"Unexpected generated challenge docs file: {path}")
        return 1
    print("Generated challenge docs are up to date.")
    return 0


def _write(outputs: dict[Path, str]) -> int:
    """Write all generated challenge docs to disk."""
    changed = 0
    for path, content in outputs.items():
        changed += int(_write_if_changed(path, content))
    print(f"Wrote {changed} generated challenge doc file(s).")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Generate or check self-contained challenge README files."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify files without writing.")
    args = parser.parse_args(argv)

    repo_root = _repo_root()
    specs = load_challenge_catalog(_catalog_root(repo_root))
    outputs = _expected_outputs(repo_root, specs)
    return _check(outputs) if args.check else _write(outputs)


if __name__ == "__main__":
    raise SystemExit(main())

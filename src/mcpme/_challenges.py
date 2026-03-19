"""Live raw-upstream challenge loading, execution, and reporting helpers.

This module intentionally sits outside the public package surface. The
challenge track is useful pressure on ``mcpme``'s ingestion quality, but it is
not part of the supported API contract for downstream users.

The harness follows the same path a real user would:

1. Read one challenge specification from deterministic TOML.
2. Generate a facade with ``scaffold_package`` or ``scaffold_command``.
3. Build a manifest from that generated facade.
4. Execute one or more live workflow steps through the normal runtime.
5. Write stable JSON, JUnit, and markdown reports.

Challenge failures are reported as challenge results rather than harness
failures so the suite can stay informative and non-gating.
"""

from __future__ import annotations

import importlib
import json
import os
import re
import shlex
import shutil
import sys
import tomllib
import traceback
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ._scaffold import ScaffoldReport, scaffold_command, scaffold_package
from .discovery import build_manifest
from .execution import ToolExecutionResult, execute_tool

_VALID_TIERS = frozenset({"gha_subset", "local_full"})
_VALID_DIFFICULTIES = frozenset({"easy", "medium", "hard", "insane"})
_VALID_TARGET_KINDS = frozenset({"package", "command"})
_VALID_STATUSES = frozenset({"passed", "failed", "skipped_unavailable"})
_PATH_TOKEN_PATTERN = re.compile(r"([^\.\[\]]+)|\[(\d+)\]")


class ChallengeCatalogError(ValueError):
    """Raised when the live challenge catalog is malformed."""


@dataclass(frozen=True, slots=True)
class ChallengeTarget:
    """Describe the raw upstream target exercised by one challenge.

    :param kind: Target family. Supported values are ``"package"`` and
        ``"command"``.
    :param value: Import path or command token sequence used for scaffolding.
    """

    kind: str
    value: str | tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ChallengeProbe:
    """Describe availability probes evaluated before a live challenge runs.

    :param imports: Import paths that must import successfully.
    :param commands: Command token sequences whose executable must be available.
    """

    imports: tuple[str, ...] = ()
    commands: tuple[tuple[str, ...], ...] = ()


@dataclass(frozen=True, slots=True)
class ChallengeWorkflowStep:
    """Describe one live workflow step executed against a generated manifest.

    :param tool: Tool name executed through the manifest runtime.
    :param arguments: Raw JSON-like arguments forwarded to the tool.
    :param label: Optional human-friendly label for reports.
    :param expect_tool_error: Whether the step expects ``is_error`` from the
        runtime.
    :param expect_text_contains: Text snippets that must appear in the returned
        content.
    :param expect_json_fields: Field assertions against parsed JSON content
        blocks.
    :param expect_structured_fields: Field assertions against
        ``structuredContent``.
    :param expect_files_exist: Files that must exist after the step finishes.
    :param expect_files_nonempty: Files that must exist and be non-empty.
    :param expect_files_missing: Files or directories that must not exist after
        the step finishes.
    :param capture_json: Values captured from parsed JSON content for later
        steps.
    """

    tool: str
    arguments: dict[str, Any] = field(default_factory=dict)
    label: str | None = None
    expect_tool_error: bool = False
    expect_text_contains: tuple[str, ...] = ()
    expect_json_fields: dict[str, Any] = field(default_factory=dict)
    expect_structured_fields: dict[str, Any] = field(default_factory=dict)
    expect_files_exist: tuple[str, ...] = ()
    expect_files_nonempty: tuple[str, ...] = ()
    expect_files_missing: tuple[str, ...] = ()
    capture_json: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ChallengeRenderedFile:
    """Describe one checked-in template rendered into the challenge workspace.

    :param source: Source template path. Relative paths are resolved from the
        challenge case directory.
    :param destination: Rendered output path. Relative paths are resolved from
        the per-run challenge artifact directory.
    """

    source: str
    destination: str


@dataclass(frozen=True, slots=True)
class ChallengeExample:
    """Capture the narrative that makes one challenge readable as an example.

    :param summary: Short plain-language overview of what the case demonstrates.
    :param motivation: Why this case matters for real engineering-tool
        wrapping.
    :param proves: Concrete capabilities the challenge is expected to prove.
    :param limitations: Optional caveats or known boundaries for the case.
    """

    summary: str
    motivation: str
    proves: tuple[str, ...]
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ChallengeIngestion:
    """Describe scaffold breadth requirements for one live challenge.

    :param min_generated_tools: Minimum number of generated tools expected from
        one-shot ingestion.
    :param required_tools: Specific tool names that must appear in the
        generated facade.
    """

    min_generated_tools: int = 0
    required_tools: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ChallengeSpec:
    """Represent one catalogued live challenge.

    :param id: Stable catalog identifier.
    :param title: Human-readable title used in reports.
    :param tier: Execution tier. ``"gha_subset"`` runs in CI; ``"local_full"``
        is local only.
    :param style: Short style label such as ``"package"`` or ``"command"``.
    :param slice: Workflow slice such as ``"aerodynamics"`` or ``"systems"``.
    :param family: Stable challenge family, used to group related difficulty
        ladders such as ``"avl"`` or ``"openmdao"``.
    :param difficulty: Challenge difficulty rung. Canonical values are
        ``"easy"``, ``"medium"``, ``"hard"``, and ``"insane"``.
    :param target: Raw upstream target definition.
    :param probe: Availability probe configuration.
    :param scaffold_kind: Scaffold entry point used for the target.
    :param scaffold_options: Deterministic scaffold options from the catalog.
    :param rendered_files: Optional rendered setup inputs materialized before
        workflow execution.
    :param ingestion: Expected breadth of the generated facade before workflow
        execution begins.
    :param workflow_steps: Workflow-step sequence executed after ingestion
        succeeds.
    :param example: Narrative metadata rendered into challenge-local README
        files.
    :param catalog_path: Checked-in ``challenge.toml`` path for the case.
    :param case_dir: Case directory containing the catalog, README, and
        fixtures.
    :param notes: Optional challenge note.
    """

    id: str
    title: str
    tier: str
    style: str
    slice: str
    target: ChallengeTarget
    probe: ChallengeProbe
    scaffold_kind: str
    scaffold_options: dict[str, Any]
    family: str = ""
    difficulty: str = ""
    rendered_files: tuple[ChallengeRenderedFile, ...] = ()
    workflow_steps: tuple[ChallengeWorkflowStep, ...] = ()
    ingestion: ChallengeIngestion = field(default_factory=ChallengeIngestion)
    example: ChallengeExample = field(
        default_factory=lambda: ChallengeExample(
            summary="Ad hoc challenge.",
            motivation="Exercise one challenge scenario.",
            proves=("Challenge harness execution.",),
        )
    )
    catalog_path: Path = Path("challenge.toml")
    case_dir: Path = Path(".")
    notes: str | None = None

    def __post_init__(self) -> None:
        """Normalize derived metadata defaults for ad hoc challenge specs."""
        if not self.family:
            object.__setattr__(self, "family", _default_family(self.id))
        if not self.difficulty:
            object.__setattr__(self, "difficulty", "medium")

    @property
    def smoke_steps(self) -> tuple[ChallengeWorkflowStep, ...]:
        """Return the legacy ``smoke_steps`` view of ``workflow_steps``."""
        return self.workflow_steps


@dataclass(frozen=True, slots=True)
class ChallengeStepResult:
    """Capture one executed workflow step result.

    :param tool: Tool name executed by the step.
    :param label: Human-readable label for reports.
    :param status: Step status.
    :param message: Summary message.
    :param captured: Captured context variables produced by the step.
    :param artifact_dir: Optional retained artifact directory for the tool
        call.
    """

    tool: str
    label: str
    status: str
    message: str
    captured: dict[str, Any] = field(default_factory=dict)
    artifact_dir: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation."""
        return {
            "tool": self.tool,
            "label": self.label,
            "status": self.status,
            "message": self.message,
            "captured": dict(self.captured),
            "artifactDir": self.artifact_dir,
        }


@dataclass(frozen=True, slots=True)
class ChallengeResult:
    """Capture the full outcome for one live challenge.

    :param id: Stable challenge identifier.
    :param title: Human-readable title.
    :param tier: Execution tier.
    :param style: Challenge style label.
    :param slice: Workflow slice label.
    :param family: Stable challenge family.
    :param difficulty: Challenge difficulty rung.
    :param status: Overall status.
    :param message: Summary message.
    :param generated_tools: Generated facade tool names.
    :param steps: Executed workflow-step results.
    :param scaffold_path: Generated facade path, when scaffold succeeded.
    :param notes: Optional challenge note.
    """

    id: str
    title: str
    tier: str
    style: str
    slice: str
    status: str
    message: str
    family: str = ""
    difficulty: str = ""
    generated_tools: tuple[str, ...] = ()
    steps: tuple[ChallengeStepResult, ...] = ()
    scaffold_path: str | None = None
    notes: str | None = None

    def __post_init__(self) -> None:
        """Normalize derived metadata defaults for ad hoc challenge results."""
        if not self.family:
            object.__setattr__(self, "family", _default_family(self.id))
        if not self.difficulty:
            object.__setattr__(self, "difficulty", "medium")

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation."""
        return {
            "id": self.id,
            "title": self.title,
            "tier": self.tier,
            "style": self.style,
            "slice": self.slice,
            "family": self.family,
            "difficulty": self.difficulty,
            "status": self.status,
            "message": self.message,
            "generatedTools": list(self.generated_tools),
            "steps": [step.to_dict() for step in self.steps],
            "scaffoldPath": self.scaffold_path,
            "notes": self.notes,
        }


# Backward-compatible alias for the previous internal terminology.
ChallengeSmokeStep = ChallengeWorkflowStep


@dataclass(frozen=True, slots=True)
class ChallengeAggregate:
    """Represent aggregate live challenge results.

    :param suite_name: Stable suite label.
    :param selected_tier: Requested execution tier.
    :param results: Ordered challenge results.
    """

    suite_name: str
    selected_tier: str
    results: tuple[ChallengeResult, ...]

    @property
    def total(self) -> int:
        """Return the total number of executed or skipped challenges."""
        return len(self.results)

    @property
    def passed(self) -> int:
        """Return the number of passing challenges."""
        return sum(result.status == "passed" for result in self.results)

    @property
    def failed(self) -> int:
        """Return the number of failing challenges."""
        return sum(result.status == "failed" for result in self.results)

    @property
    def skipped_unavailable(self) -> int:
        """Return the number of skipped-unavailable challenges."""
        return sum(result.status == "skipped_unavailable" for result in self.results)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation."""
        return {
            "suite": self.suite_name,
            "selectedTier": self.selected_tier,
            "summary": {
                "total": self.total,
                "passed": self.passed,
                "failed": self.failed,
                "skippedUnavailable": self.skipped_unavailable,
            },
            "results": [result.to_dict() for result in self.results],
        }


def load_challenge_catalog(catalog_dir: Path) -> tuple[ChallengeSpec, ...]:
    """Load and validate one challenge catalog root.

    :param catalog_dir: Directory containing challenge case directories or
        ``*.toml`` files.
    :returns: Parsed challenge specifications sorted by ``id``.
    :raises ChallengeCatalogError: Raised when catalog contents are invalid.
    """
    specs: list[ChallengeSpec] = []
    seen_ids: set[str] = set()
    for path in _discover_catalog_paths(catalog_dir):
        spec = _load_challenge_spec(path)
        if spec.id in seen_ids:
            raise ChallengeCatalogError(f"Duplicate challenge id {spec.id!r} in {path}.")
        seen_ids.add(spec.id)
        specs.append(spec)
    return tuple(sorted(specs, key=lambda spec: spec.id))


def _discover_catalog_paths(catalog_dir: Path) -> tuple[Path, ...]:
    """Discover checked-in challenge specification files from one root.

    The challenge track now prefers one directory per case so each raw-upstream
    scenario can carry its own fixtures and README. This helper still accepts
    flat ``*.toml`` directories to keep tests and local ad hoc cases simple.
    """
    if not catalog_dir.exists():
        raise ChallengeCatalogError(f"Challenge catalog directory does not exist: {catalog_dir}")
    case_paths = sorted(path for path in catalog_dir.rglob("challenge.toml") if path.is_file())
    if case_paths:
        return tuple(case_paths)
    flat_paths = sorted(path for path in catalog_dir.glob("*.toml") if path.is_file())
    return tuple(flat_paths)


def run_challenge_suite(
    specs: tuple[ChallengeSpec, ...],
    *,
    repo_root: Path,
    artifact_root: Path,
    selected_tier: str,
    selected_ids: tuple[str, ...] = (),
    selected_families: tuple[str, ...] = (),
    selected_difficulty: str = "all",
) -> ChallengeAggregate:
    """Run one live challenge suite and return aggregate results.

    :param specs: Loaded challenge specifications.
    :param repo_root: Repository root used for fixture and output paths.
    :param artifact_root: Directory receiving challenge artifacts.
    :param selected_tier: Requested tier selector. ``"all"`` runs both tiers.
    :param selected_ids: Optional explicit challenge ids to run.
    :param selected_families: Optional explicit challenge families to run.
    :param selected_difficulty: Optional difficulty selector. ``"all"``
        keeps every difficulty.
    :returns: Aggregate challenge results.
    """
    requested_ids = frozenset(selected_ids)
    requested_families = frozenset(selected_families)
    available_ids = frozenset(spec.id for spec in specs)
    missing_ids = sorted(requested_ids - available_ids)
    if missing_ids:
        raise ChallengeCatalogError(f"Unknown challenge id(s): {missing_ids!r}.")
    if selected_difficulty != "all" and selected_difficulty not in _VALID_DIFFICULTIES:
        raise ChallengeCatalogError(
            "selected_difficulty must be 'all' or one of "
            f"{sorted(_VALID_DIFFICULTIES)!r}, got {selected_difficulty!r}."
        )
    filtered_specs = tuple(
        spec
        for spec in specs
        if (selected_tier == "all" or spec.tier == selected_tier)
        and (not requested_families or spec.family in requested_families)
        and (selected_difficulty == "all" or spec.difficulty == selected_difficulty)
        and (not requested_ids or spec.id in requested_ids)
    )
    if (requested_ids or requested_families or selected_difficulty != "all") and not filtered_specs:
        raise ChallengeCatalogError(
            "Requested challenge filters do not match the selected tier filter."
        )
    results = tuple(
        _run_single_challenge(
            spec,
            repo_root=repo_root,
            suite_artifact_root=artifact_root,
        )
        for spec in filtered_specs
    )
    return ChallengeAggregate(
        suite_name="live_raw_upstream",
        selected_tier=selected_tier,
        results=results,
    )


def write_metrics_json(aggregate: ChallengeAggregate, output_path: Path) -> None:
    """Write deterministic aggregate challenge metrics as JSON."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(aggregate.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_junit_xml(aggregate: ChallengeAggregate, output_path: Path) -> None:
    """Write deterministic JUnit XML for a challenge aggregate."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    testsuite = ET.Element(
        "testsuite",
        {
            "name": "live_raw_upstream",
            "tests": str(aggregate.total),
            "failures": str(aggregate.failed),
            "errors": "0",
            "skipped": str(aggregate.skipped_unavailable),
        },
    )
    for result in aggregate.results:
        testcase = ET.SubElement(
            testsuite,
            "testcase",
            {
                "classname": f"challenge.{result.tier}.{result.family}.{result.difficulty}",
                "name": result.id,
                "file": f"challenges/cases/{result.id}/challenge.toml",
            },
        )
        system_out = ET.SubElement(testcase, "system-out")
        system_out.text = json.dumps(result.to_dict(), indent=2, sort_keys=True)
        if result.status == "failed":
            failure = ET.SubElement(testcase, "failure", {"message": result.message})
            failure.text = result.message
        elif result.status == "skipped_unavailable":
            skipped = ET.SubElement(testcase, "skipped", {"message": result.message})
            skipped.text = result.message
    tree = ET.ElementTree(testsuite)
    ET.indent(tree, space="  ")
    tree.write(output_path, encoding="utf-8", xml_declaration=True)


def render_summary_markdown(aggregate: ChallengeAggregate) -> str:
    """Render a stable markdown summary for one challenge aggregate."""
    lines = [
        "# Live Raw-Upstream Challenges",
        "",
        (
            f"Ran `{aggregate.total}` challenges for tier `{aggregate.selected_tier}`: "
            f"`{aggregate.passed}` passed, `{aggregate.failed}` failed, "
            f"`{aggregate.skipped_unavailable}` skipped as unavailable."
        ),
        "",
        "| Challenge | Family | Difficulty | Tier | Status | Details |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for result in aggregate.results:
        lines.append(
            f"| `{result.id}` | `{result.family}` | `{result.difficulty}` | "
            f"`{result.tier}` | `{result.status}` | {result.message} |"
        )
    return "\n".join(lines) + "\n"


def write_summary_markdown(aggregate: ChallengeAggregate, output_path: Path) -> None:
    """Write a stable markdown summary for one challenge aggregate."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_summary_markdown(aggregate), encoding="utf-8")


def render_badge_svg(aggregate: ChallengeAggregate) -> str:
    """Render a compact SVG badge for the reduced live challenge subset."""
    message = f"{aggregate.passed}/{aggregate.total} pass"
    color = _badge_color(aggregate)
    return _render_badge(label="Challenges Live", message=message, color=color)


def _load_challenge_spec(path: Path) -> ChallengeSpec:
    """Load one TOML challenge specification from disk."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    challenge_id = _require_string(data, "id", path)
    title = _require_string(data, "title", path)
    tier = _require_string(data, "tier", path)
    if tier not in _VALID_TIERS:
        raise ChallengeCatalogError(
            f"{path}: tier must be one of {sorted(_VALID_TIERS)!r}, got {tier!r}."
        )
    style = _require_string(data, "style", path)
    workflow_slice = _require_string(data, "slice", path)
    family_value = data.get("family")
    if family_value is None:
        family = _default_family(challenge_id)
    elif isinstance(family_value, str) and family_value.strip():
        family = family_value.strip()
    else:
        raise ChallengeCatalogError(f"{path}: family must be a non-empty string when provided.")
    difficulty_value = data.get("difficulty", "medium")
    if not isinstance(difficulty_value, str) or not difficulty_value.strip():
        raise ChallengeCatalogError(f"{path}: difficulty must be a non-empty string.")
    difficulty = difficulty_value.strip()
    if difficulty not in _VALID_DIFFICULTIES:
        raise ChallengeCatalogError(
            f"{path}: difficulty must be one of {sorted(_VALID_DIFFICULTIES)!r}, got "
            f"{difficulty!r}."
        )
    target_data = _require_table(data, "target", path)
    target_kind = _require_string(target_data, "kind", path)
    if target_kind not in _VALID_TARGET_KINDS:
        raise ChallengeCatalogError(
            f"{path}: target.kind must be one of {sorted(_VALID_TARGET_KINDS)!r}, got "
            f"{target_kind!r}."
        )
    target = ChallengeTarget(
        kind=target_kind,
        value=_parse_target_value(target_kind, target_data.get("value"), path),
    )
    probe_data = _optional_table(data, "probe")
    probe = ChallengeProbe(
        imports=_parse_import_list(probe_data.get("imports", ()), path),
        commands=_parse_command_sequence_list(probe_data.get("commands", ()), path),
    )
    scaffold_data = _require_table(data, "scaffold", path)
    scaffold_kind = _require_string(scaffold_data, "kind", path)
    if scaffold_kind not in _VALID_TARGET_KINDS:
        raise ChallengeCatalogError(
            f"{path}: scaffold.kind must be one of {sorted(_VALID_TARGET_KINDS)!r}, got "
            f"{scaffold_kind!r}."
        )
    if scaffold_kind != target.kind:
        raise ChallengeCatalogError(
            f"{path}: scaffold.kind {scaffold_kind!r} must match target.kind {target.kind!r}."
        )
    scaffold_options = {key: value for key, value in scaffold_data.items() if key != "kind"}
    ingestion = _parse_ingestion(_optional_table(data, "ingestion"), path)
    if "workflow" in data and "smoke" in data:
        raise ChallengeCatalogError(f"{path}: use either [workflow] or legacy [smoke], not both.")
    workflow_data = _optional_table(data, "workflow")
    if not workflow_data and "smoke" in data:
        workflow_data = _optional_table(data, "smoke")
    if not workflow_data:
        raise ChallengeCatalogError(f"{path}: field 'workflow' must be a table.")
    raw_steps = workflow_data.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise ChallengeCatalogError(f"{path}: workflow.steps must be a non-empty array of tables.")
    workflow_steps = tuple(_parse_workflow_step(step_data, path) for step_data in raw_steps)
    example = _parse_example(_require_table(data, "example", path), path)
    notes = data.get("notes")
    if notes is not None and not isinstance(notes, str):
        raise ChallengeCatalogError(f"{path}: notes must be a string when provided.")
    setup_data = _optional_table(data, "setup")
    rendered_files = _parse_rendered_files(setup_data.get("rendered_files", ()), path)
    return ChallengeSpec(
        id=challenge_id,
        title=title,
        tier=tier,
        style=style,
        slice=workflow_slice,
        family=family,
        difficulty=difficulty,
        target=target,
        probe=probe,
        scaffold_kind=scaffold_kind,
        scaffold_options=scaffold_options,
        rendered_files=rendered_files,
        workflow_steps=workflow_steps,
        ingestion=ingestion,
        example=example,
        catalog_path=path,
        case_dir=path.parent,
        notes=notes,
    )


def _parse_example(example_data: dict[str, Any], path: Path) -> ChallengeExample:
    """Parse one required example table from a challenge catalog file."""
    summary = _require_string(example_data, "summary", path)
    motivation = _require_string(example_data, "motivation", path)
    proves = _parse_string_tuple(example_data.get("proves", ()), path)
    if not proves:
        raise ChallengeCatalogError(f"{path}: example.proves must contain at least one item.")
    limitations = _parse_string_tuple(example_data.get("limitations", ()), path)
    return ChallengeExample(
        summary=summary,
        motivation=motivation,
        proves=proves,
        limitations=limitations,
    )


def _default_family(challenge_id: str) -> str:
    """Derive a stable challenge family label from one challenge id."""
    return challenge_id.split("_", 1)[0] or challenge_id


def _parse_rendered_files(value: Any, path: Path) -> tuple[ChallengeRenderedFile, ...]:
    """Parse optional rendered setup files from one challenge catalog."""
    if value is None or value == ():
        return ()
    if not isinstance(value, list):
        raise ChallengeCatalogError(f"{path}: setup.rendered_files must be an array of tables.")
    rendered_files: list[ChallengeRenderedFile] = []
    for item in value:
        if not isinstance(item, dict):
            raise ChallengeCatalogError(f"{path}: setup.rendered_files entries must be tables.")
        rendered_files.append(
            ChallengeRenderedFile(
                source=_require_string(item, "source", path),
                destination=_require_string(item, "destination", path),
            )
        )
    return tuple(rendered_files)


def _parse_ingestion(ingestion_data: dict[str, Any], path: Path) -> ChallengeIngestion:
    """Parse optional scaffold breadth expectations from one challenge catalog."""
    min_generated_tools = ingestion_data.get("min_generated_tools", 0)
    if (
        isinstance(min_generated_tools, bool)
        or not isinstance(min_generated_tools, int)
        or min_generated_tools < 0
    ):
        raise ChallengeCatalogError(
            f"{path}: ingestion.min_generated_tools must be a non-negative integer."
        )
    required_tools = _parse_string_tuple(ingestion_data.get("required_tools", ()), path)
    return ChallengeIngestion(
        min_generated_tools=min_generated_tools,
        required_tools=required_tools,
    )


def _parse_workflow_step(step_data: Any, path: Path) -> ChallengeWorkflowStep:
    """Normalize one TOML workflow-step table into a dataclass."""
    if not isinstance(step_data, dict):
        raise ChallengeCatalogError(f"{path}: workflow.steps entries must be tables.")
    tool = _require_string(step_data, "tool", path)
    label = step_data.get("label")
    if label is not None and not isinstance(label, str):
        raise ChallengeCatalogError(f"{path}: workflow step label must be a string.")
    arguments = step_data.get("arguments", {})
    if not isinstance(arguments, dict):
        raise ChallengeCatalogError(f"{path}: workflow step arguments must be a table.")
    expect_data = _optional_table(step_data, "expect")
    capture_json = step_data.get("capture_json", {})
    if not isinstance(capture_json, dict):
        raise ChallengeCatalogError(f"{path}: workflow step capture_json must be a table.")
    normalized_capture = {
        _coerce_capture_name(key, path): _coerce_json_path(value, path)
        for key, value in capture_json.items()
    }
    return ChallengeWorkflowStep(
        tool=tool,
        arguments=dict(arguments),
        label=label,
        expect_tool_error=bool(expect_data.get("tool_error", False)),
        expect_text_contains=_parse_string_tuple(expect_data.get("text_contains", ()), path),
        expect_json_fields=_parse_expectation_table(expect_data.get("json_fields", {}), path),
        expect_structured_fields=_parse_expectation_table(
            expect_data.get("structured_fields", {}),
            path,
        ),
        expect_files_exist=_parse_string_tuple(expect_data.get("files_exist", ()), path),
        expect_files_nonempty=_parse_string_tuple(expect_data.get("files_nonempty", ()), path),
        expect_files_missing=_parse_string_tuple(expect_data.get("files_missing", ()), path),
        capture_json=normalized_capture,
    )


def _run_single_challenge(
    spec: ChallengeSpec,
    *,
    repo_root: Path,
    suite_artifact_root: Path,
) -> ChallengeResult:
    """Execute one challenge and capture it as a result object."""
    challenge_dir = suite_artifact_root / spec.id
    if challenge_dir.exists():
        shutil.rmtree(challenge_dir)
    challenge_dir.mkdir(parents=True, exist_ok=True)
    # Each case owns its own fixtures so the challenge directory reads like a
    # compact example rather than a detached catalog entry plus shared assets.
    fixture_dir = spec.case_dir / "fixtures"
    context = _base_context(
        repo_root=repo_root,
        challenge_dir=challenge_dir,
        fixture_dir=fixture_dir,
    )
    availability_message = _probe_availability(spec, context)
    if availability_message is not None:
        result = ChallengeResult(
            id=spec.id,
            title=spec.title,
            tier=spec.tier,
            style=spec.style,
            slice=spec.slice,
            family=spec.family,
            difficulty=spec.difficulty,
            status="skipped_unavailable",
            message=availability_message,
            notes=spec.notes,
        )
        _write_challenge_result(challenge_dir, result)
        return result

    try:
        with _pushd(challenge_dir):
            _materialize_rendered_files(
                spec.rendered_files,
                case_dir=spec.case_dir,
                challenge_dir=challenge_dir,
                context=context,
            )
            scaffold_path = challenge_dir / "generated_facade.py"
            scaffold_report = _run_scaffold(
                spec,
                scaffold_path=scaffold_path,
                context=context,
            )
            generated_tools = tuple(tool.name for tool in scaffold_report.generated_tools)
            ingestion_message = _validate_ingestion(spec.ingestion, generated_tools)
            if ingestion_message is not None:
                result = ChallengeResult(
                    id=spec.id,
                    title=spec.title,
                    tier=spec.tier,
                    style=spec.style,
                    slice=spec.slice,
                    family=spec.family,
                    difficulty=spec.difficulty,
                    status="failed",
                    message=ingestion_message,
                    generated_tools=generated_tools,
                    scaffold_path=str(scaffold_path),
                    notes=spec.notes,
                )
                _write_challenge_result(challenge_dir, result)
                return result
            manifest = build_manifest(
                targets=[scaffold_path],
                artifact_root=challenge_dir / "tool_artifacts",
            )
            step_results: list[ChallengeStepResult] = []
            for step in spec.workflow_steps:
                step_result = _execute_workflow_step(
                    manifest=manifest,
                    step=step,
                    context=context,
                    challenge_dir=challenge_dir,
                )
                step_results.append(step_result)
                if step_result.status != "passed":
                    result = ChallengeResult(
                        id=spec.id,
                        title=spec.title,
                        tier=spec.tier,
                        style=spec.style,
                        slice=spec.slice,
                        family=spec.family,
                        difficulty=spec.difficulty,
                        status="failed",
                        message=step_result.message,
                        generated_tools=generated_tools,
                        steps=tuple(step_results),
                        scaffold_path=str(scaffold_path),
                        notes=spec.notes,
                    )
                    _write_challenge_result(challenge_dir, result)
                    return result
        result = ChallengeResult(
            id=spec.id,
            title=spec.title,
            tier=spec.tier,
            style=spec.style,
            slice=spec.slice,
            family=spec.family,
            difficulty=spec.difficulty,
            status="passed",
            message="All scaffold and workflow steps passed.",
            generated_tools=generated_tools,
            steps=tuple(step_results),
            scaffold_path=str(scaffold_path),
            notes=spec.notes,
        )
        _write_challenge_result(challenge_dir, result)
        return result
    except Exception as error:
        detail = "".join(traceback.format_exception_only(type(error), error)).strip()
        traceback_path = challenge_dir / "failure_traceback.txt"
        traceback_path.write_text(traceback.format_exc(), encoding="utf-8")
        result = ChallengeResult(
            id=spec.id,
            title=spec.title,
            tier=spec.tier,
            style=spec.style,
            slice=spec.slice,
            family=spec.family,
            difficulty=spec.difficulty,
            status="failed",
            message=detail,
            notes=spec.notes,
        )
        _write_challenge_result(challenge_dir, result)
        return result


def _run_scaffold(
    spec: ChallengeSpec,
    *,
    scaffold_path: Path,
    context: dict[str, Any],
) -> ScaffoldReport:
    """Generate one facade module for a challenge target."""
    rendered_options = _render_value(spec.scaffold_options, context)
    if spec.scaffold_kind == "package":
        package_name = _render_package_target(spec.target, context)
        return scaffold_package(
            package_name,
            scaffold_path,
            **_normalize_package_scaffold_options(rendered_options),
        )
    command = _render_command_target(spec.target, context)
    return scaffold_command(
        command,
        scaffold_path,
        **_normalize_command_scaffold_options(rendered_options),
    )


def _materialize_rendered_files(
    rendered_files: tuple[ChallengeRenderedFile, ...],
    *,
    case_dir: Path,
    challenge_dir: Path,
    context: dict[str, Any],
) -> None:
    """Render checked-in template files into one challenge artifact directory."""
    for rendered_file in rendered_files:
        source_value = _render_string(rendered_file.source, context)
        destination_value = _render_string(rendered_file.destination, context)
        source_path = Path(source_value)
        if not source_path.is_absolute():
            source_path = case_dir / source_path
        destination_path = _resolve_expected_path(destination_value, challenge_dir)
        rendered_text = _render_string(source_path.read_text(encoding="utf-8"), context)
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        destination_path.write_text(rendered_text, encoding="utf-8")


@contextmanager
def _pushd(path: Path) -> Iterator[None]:
    """Temporarily switch the process working directory.

    Live upstream engineering tools often emit scratch files relative to the
    current working directory. The challenge harness runs each challenge inside
    its own artifact directory so those upstream side effects stay isolated and
    inspectable instead of polluting the repository root.

    :param path: Directory that should become the temporary working directory.
    :yields: ``None`` while the working directory is changed.
    """
    previous_cwd = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous_cwd)


def _execute_workflow_step(
    *,
    manifest: Any,
    step: ChallengeWorkflowStep,
    context: dict[str, Any],
    challenge_dir: Path,
) -> ChallengeStepResult:
    """Execute and validate one workflow step."""
    rendered_arguments = _render_value(step.arguments, context)
    if not isinstance(rendered_arguments, dict):
        raise ChallengeCatalogError("Rendered step arguments must be a mapping.")
    normalized_arguments = _normalize_step_arguments_for_tool(
        manifest=manifest,
        tool_name=step.tool,
        arguments=rendered_arguments,
    )
    result = execute_tool(manifest, step.tool, normalized_arguments)
    return _validate_step_result(
        result=result,
        step=step,
        context=context,
        challenge_dir=challenge_dir,
    )


def _validate_step_result(
    *,
    result: ToolExecutionResult,
    step: ChallengeWorkflowStep,
    context: dict[str, Any],
    challenge_dir: Path,
) -> ChallengeStepResult:
    """Validate one executed workflow step and capture follow-on context."""
    content_text = "\n".join(
        block.get("text", "") for block in result.content if block.get("type") == "text"
    )
    parsed_json = _parse_content_json(result)
    captured: dict[str, Any] = {}
    label = step.label or step.tool

    if result.is_error != step.expect_tool_error:
        return ChallengeStepResult(
            tool=step.tool,
            label=label,
            status="failed",
            message=(
                f"Expected tool_error={step.expect_tool_error}, got is_error={result.is_error}."
            ),
            artifact_dir=_artifact_dir_string(result),
        )

    for snippet in step.expect_text_contains:
        rendered_snippet = _render_string(snippet, context)
        if rendered_snippet not in content_text:
            return ChallengeStepResult(
                tool=step.tool,
                label=label,
                status="failed",
                message=f"Missing expected text snippet: {rendered_snippet!r}.",
                artifact_dir=_artifact_dir_string(result),
            )

    for json_path, expected_value in sorted(step.expect_json_fields.items()):
        if parsed_json is None:
            return ChallengeStepResult(
                tool=step.tool,
                label=label,
                status="failed",
                message="Expected JSON content, but the tool returned non-JSON text.",
                artifact_dir=_artifact_dir_string(result),
            )
        rendered_expected = _render_value(expected_value, context)
        actual = _extract_path_value(parsed_json, json_path)
        if actual != rendered_expected:
            return ChallengeStepResult(
                tool=step.tool,
                label=label,
                status="failed",
                message=(
                    f"JSON field {json_path!r} expected {rendered_expected!r}, got {actual!r}."
                ),
                artifact_dir=_artifact_dir_string(result),
            )

    for json_path, expected_value in sorted(step.expect_structured_fields.items()):
        if result.structured_content is None:
            return ChallengeStepResult(
                tool=step.tool,
                label=label,
                status="failed",
                message="Expected structured content, but the tool returned none.",
                artifact_dir=_artifact_dir_string(result),
            )
        rendered_expected = _render_value(expected_value, context)
        actual = _extract_path_value(result.structured_content, json_path)
        if actual != rendered_expected:
            return ChallengeStepResult(
                tool=step.tool,
                label=label,
                status="failed",
                message=(
                    f"Structured field {json_path!r} expected {rendered_expected!r}, "
                    f"got {actual!r}."
                ),
                artifact_dir=_artifact_dir_string(result),
            )

    for raw_path in step.expect_files_exist:
        path = _resolve_expected_path(_render_string(raw_path, context), challenge_dir)
        if not path.exists():
            return ChallengeStepResult(
                tool=step.tool,
                label=label,
                status="failed",
                message=f"Expected file or directory {str(path)!r} to exist.",
                artifact_dir=_artifact_dir_string(result),
            )

    for raw_path in step.expect_files_nonempty:
        path = _resolve_expected_path(_render_string(raw_path, context), challenge_dir)
        if not path.exists():
            return ChallengeStepResult(
                tool=step.tool,
                label=label,
                status="failed",
                message=f"Expected file {str(path)!r} to exist.",
                artifact_dir=_artifact_dir_string(result),
            )
        if not path.is_file() or path.stat().st_size == 0:
            return ChallengeStepResult(
                tool=step.tool,
                label=label,
                status="failed",
                message=f"Expected file {str(path)!r} to be non-empty.",
                artifact_dir=_artifact_dir_string(result),
            )

    for raw_path in step.expect_files_missing:
        path = _resolve_expected_path(_render_string(raw_path, context), challenge_dir)
        if path.exists():
            return ChallengeStepResult(
                tool=step.tool,
                label=label,
                status="failed",
                message=f"Expected file or directory {str(path)!r} to be missing.",
                artifact_dir=_artifact_dir_string(result),
            )

    for capture_name, json_path in sorted(step.capture_json.items()):
        if parsed_json is None:
            return ChallengeStepResult(
                tool=step.tool,
                label=label,
                status="failed",
                message="capture_json requested JSON content, but the tool returned non-JSON text.",
                artifact_dir=_artifact_dir_string(result),
            )
        captured_value = _extract_path_value(parsed_json, json_path)
        context[capture_name] = captured_value
        captured[capture_name] = captured_value

    return ChallengeStepResult(
        tool=step.tool,
        label=label,
        status="passed",
        message="Workflow step passed.",
        captured=captured,
        artifact_dir=_artifact_dir_string(result),
    )


def _probe_availability(spec: ChallengeSpec, context: dict[str, Any]) -> str | None:
    """Return a skip message when a challenge target is unavailable."""
    for import_name in spec.probe.imports:
        rendered_import = _render_string(import_name, context)
        try:
            importlib.import_module(rendered_import)
        except Exception as error:
            return f"Availability probe import failed for {rendered_import!r}: {error}"
    for command_tokens in spec.probe.commands:
        rendered_tokens = tuple(_render_string(token, context) for token in command_tokens)
        executable = rendered_tokens[0]
        if os.path.sep in executable:
            if not Path(executable).exists():
                return f"Availability probe command path is missing: {executable!r}"
            continue
        search_path = os.pathsep.join([str(context["venv_bin_dir"]), os.environ.get("PATH", "")])
        if shutil.which(executable, path=search_path) is None:
            return f"Availability probe command is unavailable on PATH: {executable!r}"
    return None


def _validate_ingestion(
    ingestion: ChallengeIngestion,
    generated_tools: tuple[str, ...],
) -> str | None:
    """Return an explicit failure message when scaffold breadth is too narrow."""
    failures: list[str] = []
    if len(generated_tools) < ingestion.min_generated_tools:
        failures.append(
            "expected at least "
            f"{ingestion.min_generated_tools} generated tools, got {len(generated_tools)}"
        )
    missing_tools = [
        tool_name for tool_name in ingestion.required_tools if tool_name not in generated_tools
    ]
    if missing_tools:
        failures.append(f"missing required generated tools {missing_tools!r}")
    if not failures:
        return None
    return f"Ingestion breadth check failed: {'; '.join(failures)}."


def _write_challenge_result(challenge_dir: Path, result: ChallengeResult) -> None:
    """Persist one per-challenge result payload for local inspection."""
    (challenge_dir / "result.json").write_text(
        json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _base_context(
    *,
    repo_root: Path,
    challenge_dir: Path,
    fixture_dir: Path,
) -> dict[str, Any]:
    """Build the base template context shared by one challenge run."""
    # Keep the active interpreter path intact so symlinked venv shims preserve
    # their environment semantics when helper scripts are launched later.
    python_executable = Path(sys.executable)
    venv_bin_dir = Path(sys.prefix).resolve() / ("Scripts" if os.name == "nt" else "bin")
    return {
        "repo_root": str(repo_root.resolve()),
        "challenge_root": str((repo_root / "challenges").resolve()),
        "challenge_artifact_dir": str(challenge_dir.resolve()),
        "challenge_fixture_dir": str(fixture_dir.resolve()),
        "python_executable": str(python_executable),
        "venv_bin_dir": str(venv_bin_dir),
        "pathsep": os.pathsep,
        "env_PATH": os.environ.get("PATH", ""),
    }


def _normalize_package_scaffold_options(options: dict[str, Any]) -> dict[str, Any]:
    """Normalize package scaffold options parsed from TOML."""
    normalized = dict(options)
    for key in (
        "module_include_patterns",
        "module_exclude_patterns",
        "symbol_include_patterns",
        "symbol_exclude_patterns",
    ):
        if key in normalized:
            normalized[key] = _tuple_from_iterable_of_strings(normalized[key], key)
    return normalized


def _normalize_command_scaffold_options(options: dict[str, Any]) -> dict[str, Any]:
    """Normalize command scaffold options parsed from TOML."""
    normalized = dict(options)
    if "help_probe_args" in normalized:
        normalized["help_probe_args"] = _tuple_from_iterable_of_strings(
            normalized["help_probe_args"],
            "help_probe_args",
        )
    return normalized


def _render_package_target(target: ChallengeTarget, context: dict[str, Any]) -> str:
    """Render one package target name from template context."""
    if not isinstance(target.value, str):
        raise ChallengeCatalogError("Package challenge target.value must be a string.")
    return _render_string(target.value, context)


def _render_command_target(target: ChallengeTarget, context: dict[str, Any]) -> tuple[str, ...]:
    """Render one command target token sequence from template context."""
    if isinstance(target.value, str):
        return tuple(_render_string(token, context) for token in shlex.split(target.value))
    return tuple(_render_string(token, context) for token in target.value)


def _render_value(value: Any, context: dict[str, Any]) -> Any:
    """Render string templates recursively within JSON-like values."""
    if isinstance(value, str):
        return _render_string(value, context)
    if isinstance(value, list):
        return [_render_value(item, context) for item in value]
    if isinstance(value, tuple):
        return tuple(_render_value(item, context) for item in value)
    if isinstance(value, dict):
        return {key: _render_value(item, context) for key, item in value.items()}
    return value


def _render_string(template: str, context: dict[str, Any]) -> str:
    """Render one ``str.format`` template with explicit missing-key errors."""
    try:
        return template.format_map(context)
    except KeyError as error:
        raise ChallengeCatalogError(
            f"Unknown template key {error.args[0]!r} in {template!r}."
        ) from error


def _parse_content_json(result: ToolExecutionResult) -> Any | None:
    """Parse the first text content block as JSON when possible."""
    for block in result.content:
        if block.get("type") != "text":
            continue
        try:
            return json.loads(block.get("text", ""))
        except json.JSONDecodeError:
            return None
    return None


def _extract_path_value(payload: Any, path: str) -> Any:
    """Extract one dotted path from nested JSON-like content."""
    if path in {"", "$"}:
        return payload
    current = payload
    for token in _path_tokens(path):
        if isinstance(token, int):
            if not isinstance(current, list):
                raise KeyError(path)
            current = current[token]
            continue
        if not isinstance(current, dict):
            raise KeyError(path)
        current = current[token]
    return current


def _path_tokens(path: str) -> tuple[str | int, ...]:
    """Split a dotted path with optional list indices into tokens."""
    matches = _PATH_TOKEN_PATTERN.findall(path)
    if not matches:
        raise ChallengeCatalogError(f"Unsupported JSON path syntax: {path!r}.")
    tokens: list[str | int] = []
    for name_token, index_token in matches:
        if name_token:
            tokens.append(name_token)
        else:
            tokens.append(int(index_token))
    return tuple(tokens)


def _resolve_expected_path(value: str, challenge_dir: Path) -> Path:
    """Resolve one expected output path relative to the challenge artifact directory."""
    path = Path(value)
    if path.is_absolute():
        return path
    return challenge_dir / path


def _artifact_dir_string(result: ToolExecutionResult) -> str | None:
    """Return the artifact directory path for one tool execution result."""
    return None if result.artifact_dir is None else str(result.artifact_dir)


def _normalize_step_arguments_for_tool(
    *,
    manifest: Any,
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Adapt common command-wrapper argument names to the discovered tool schema."""
    tool = manifest.get_tool(tool_name)
    properties = tool.input_schema.get("properties", {})
    normalized = dict(arguments)
    if "extra_argv" in normalized and "extra_argv" not in properties and "argv" in properties:
        normalized["argv"] = normalized.pop("extra_argv")
    elif "argv" in normalized and "argv" not in properties and "extra_argv" in properties:
        normalized["extra_argv"] = normalized.pop("argv")
    return normalized


def _parse_target_value(kind: str, value: Any, path: Path) -> str | tuple[str, ...]:
    """Normalize one target value from TOML."""
    if kind == "package":
        if not isinstance(value, str):
            raise ChallengeCatalogError(f"{path}: package target.value must be a string.")
        return value
    return _parse_command_tokens(value, path)


def _parse_command_sequence_list(value: Any, path: Path) -> tuple[tuple[str, ...], ...]:
    """Normalize one list of command token sequences from TOML."""
    if value is None or value == ():
        return ()
    if not isinstance(value, list):
        raise ChallengeCatalogError(f"{path}: probe.commands must be an array.")
    return tuple(_parse_command_tokens(item, path) for item in value)


def _parse_command_tokens(value: Any, path: Path) -> tuple[str, ...]:
    """Normalize one command token sequence from TOML."""
    if isinstance(value, str):
        tokens = tuple(shlex.split(value))
    elif isinstance(value, list) and all(isinstance(item, str) for item in value):
        tokens = tuple(value)
    else:
        raise ChallengeCatalogError(
            f"{path}: command values must be a string or an array of strings."
        )
    if not tokens:
        raise ChallengeCatalogError(f"{path}: command values must not be empty.")
    return tokens


def _parse_import_list(value: Any, path: Path) -> tuple[str, ...]:
    """Normalize one list of import-path probes from TOML."""
    if value is None or value == ():
        return ()
    return _parse_string_tuple(value, path)


def _parse_string_tuple(value: Any, path: Path) -> tuple[str, ...]:
    """Normalize one TOML array of strings."""
    if value is None or value == ():
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ChallengeCatalogError(f"{path}: expected an array of strings.")
    return tuple(value)


def _parse_expectation_table(value: Any, path: Path) -> dict[str, Any]:
    """Normalize one expectation table from TOML."""
    if value is None or value == {}:
        return {}
    if not isinstance(value, dict):
        raise ChallengeCatalogError(f"{path}: expectation fields must be TOML tables.")
    return {str(key): item for key, item in sorted(value.items())}


def _require_string(data: dict[str, Any], key: str, path: Path) -> str:
    """Return one required string field from a TOML table."""
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ChallengeCatalogError(f"{path}: field {key!r} must be a non-empty string.")
    return value


def _require_table(data: dict[str, Any], key: str, path: Path) -> dict[str, Any]:
    """Return one required TOML table."""
    value = data.get(key)
    if not isinstance(value, dict):
        raise ChallengeCatalogError(f"{path}: field {key!r} must be a table.")
    return value


def _optional_table(data: dict[str, Any], key: str) -> dict[str, Any]:
    """Return one optional TOML table, or an empty mapping."""
    value = data.get(key, {})
    if not isinstance(value, dict):
        raise ChallengeCatalogError(f"Field {key!r} must be a table when provided.")
    return value


def _coerce_capture_name(value: Any, path: Path) -> str:
    """Validate one capture variable name from TOML."""
    if not isinstance(value, str) or not value:
        raise ChallengeCatalogError(f"{path}: capture_json keys must be non-empty strings.")
    return value


def _coerce_json_path(value: Any, path: Path) -> str:
    """Validate one captured JSON path from TOML."""
    if not isinstance(value, str) or not value:
        raise ChallengeCatalogError(f"{path}: capture_json values must be non-empty strings.")
    return value


def _tuple_from_iterable_of_strings(value: Any, field_name: str) -> tuple[str, ...]:
    """Return one tuple of strings for scaffold options."""
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ChallengeCatalogError(f"{field_name!r} must be an array of strings.")
    return tuple(value)


def _badge_color(aggregate: ChallengeAggregate) -> str:
    """Choose a badge color from aggregate results."""
    if aggregate.total == 0:
        return "#9f9f9f"
    if aggregate.failed == 0 and aggregate.skipped_unavailable == 0:
        return "#4c1"
    if aggregate.failed == 0:
        return "#dfb317"
    if aggregate.passed == 0:
        return "#e05d44"
    return "#fe7d37"


def _render_badge(*, label: str, message: str, color: str) -> str:
    """Render one deterministic Shields-style SVG badge."""
    label_width = _badge_text_width(label)
    message_width = _badge_text_width(message)
    total_width = label_width + message_width
    label_x = label_width / 2
    message_x = label_width + (message_width / 2)
    svg_open = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{total_width}" '
        f'height="20" role="img" aria-label="{label}: {message}">'
    )
    text_group = (
        '  <g fill="#fff" text-anchor="middle" '
        'font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11">'
    )
    return f"""{svg_open}
  <linearGradient id="g" x2="0" y2="100%">
    <stop offset="0" stop-color="#fff" stop-opacity=".7"/>
    <stop offset=".1" stop-color="#aaa" stop-opacity=".1"/>
    <stop offset=".9" stop-opacity=".3"/>
    <stop offset="1" stop-opacity=".5"/>
  </linearGradient>
  <clipPath id="r">
    <rect width="{total_width}" height="20" rx="3" fill="#fff"/>
  </clipPath>
  <g clip-path="url(#r)">
    <rect width="{label_width}" height="20" fill="#555"/>
    <rect x="{label_width}" width="{message_width}" height="20" fill="{color}"/>
    <rect width="{total_width}" height="20" fill="url(#g)"/>
  </g>
{text_group}
    <text x="{label_x:.1f}" y="15" fill="#010101" fill-opacity=".3">{label}</text>
    <text x="{label_x:.1f}" y="14">{label}</text>
    <text x="{message_x:.1f}" y="15" fill="#010101" fill-opacity=".3">{message}</text>
    <text x="{message_x:.1f}" y="14">{message}</text>
  </g>
</svg>
"""


def _badge_text_width(text: str) -> int:
    """Approximate badge text width deterministically."""
    return 10 + (len(text) * 6)

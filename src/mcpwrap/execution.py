"""Deterministic execution helpers for generated tool manifests."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import importlib
import inspect
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast, get_type_hints
from uuid import uuid4

from ._python_tools import load_module_from_path, resolve_qualname
from .manifest import (
    ArgparseOptionSpec,
    FileTemplate,
    Manifest,
    RetainedPathSpec,
    SubprocessResultSpec,
    ToolManifest,
)
from .schema import SchemaValidationError, coerce_value, to_json_compatible, validate_value


@dataclass(frozen=True, slots=True)
class PythonCallableBinding:
    """Bind a manifest entry to an in-process Python callable.

    :param callable_obj: Callable object invoked directly at runtime.
    """

    callable_obj: Callable[..., Any]


@dataclass(frozen=True, slots=True)
class PythonModuleBinding:
    """Bind a manifest entry to a lazily imported module callable.

    :param module_name: Importable module path containing the callable.
    :param qualname: Object qualname resolved within the imported module.
    """

    module_name: str
    qualname: str


@dataclass(frozen=True, slots=True)
class PythonFileBinding:
    """Bind a manifest entry to a lazily loaded Python file callable.

    :param file_path: Filesystem path containing the callable definition.
    :param qualname: Object qualname resolved within the loaded file module.
    """

    file_path: str
    qualname: str


@dataclass(frozen=True, slots=True)
class SubprocessBinding:
    """Bind a manifest entry to a deterministic subprocess invocation.

    :param argv: Command-line template.
    :param cwd: Optional working directory template.
    :param env: Environment variable templates.
    :param stdin_template: Optional standard input template.
    :param files: Rendered input file templates.
    :param retained_paths: Explicit output paths copied into retained artifacts.
    :param result: Result extraction rule.
    :param timeout_seconds: Optional subprocess timeout in seconds.
    """

    argv: tuple[str, ...]
    cwd: str | None = None
    env: dict[str, str] | None = None
    stdin_template: str | None = None
    files: tuple[FileTemplate, ...] = ()
    retained_paths: tuple[RetainedPathSpec, ...] = ()
    result: SubprocessResultSpec = field(default_factory=SubprocessResultSpec)
    timeout_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class ArgparseCommandBinding:
    """Bind a manifest entry to an ``argparse``-described command.

    :param command: Command prefix used to execute the CLI.
    :param actions: Serializable parser action specifications.
    """

    command: tuple[str, ...]
    actions: tuple[ArgparseOptionSpec, ...]


@dataclass(frozen=True, slots=True)
class PreparedSubprocessRun:
    """Represent one fully rendered subprocess invocation.

    :param rendered_argv: Fully rendered command-line arguments.
    :param rendered_env: Rendered environment overrides.
    :param stdin_text: Optional rendered standard input payload.
    :param command_cwd: Effective working directory for the subprocess.
    :param rendered_files: Input file paths written before execution.
    """

    rendered_argv: tuple[str, ...]
    rendered_env: dict[str, str]
    stdin_text: str | None
    command_cwd: Path
    rendered_files: list[str]


@dataclass(frozen=True, slots=True)
class ToolExecutionResult:
    """Represent one executed tool call.

    :param content: MCP-compatible content blocks.
    :param structured_content: Optional structured result payload.
    :param artifact_dir: Optional artifact directory retained on disk.
    :param is_error: Whether execution ended in a tool-level error.
    :param meta: Optional MCP ``_meta`` extension payload.
    """

    content: tuple[dict[str, str], ...]
    structured_content: dict[str, Any] | None = None
    artifact_dir: Path | None = None
    is_error: bool = False
    meta: dict[str, Any] | None = None

    def to_mcp_result(self) -> dict[str, Any]:
        """Return the MCP ``tools/call`` payload."""
        result: dict[str, Any] = {"content": list(self.content)}
        if self.structured_content is not None:
            result["structuredContent"] = self.structured_content
        if self.is_error:
            result["isError"] = True
        if self.meta:
            result["_meta"] = self.meta
        return result


def execute_tool(manifest: Manifest, name: str, arguments: dict[str, Any]) -> ToolExecutionResult:
    """Execute one manifest tool with deterministic validation and capture.

    :param manifest: Loaded manifest to execute against.
    :param name: Tool name or deterministic alias to invoke.
    :param arguments: Raw JSON-compatible arguments.
    :returns: The normalized execution result.
    """
    tool = manifest.get_tool(name)
    validate_value(arguments, tool.input_schema)
    artifact_mode = manifest.artifact_policy.mode
    artifact_dir = _create_artifact_dir(manifest, tool.name)
    try:
        binding = manifest.get_binding(name)
        if isinstance(binding, (PythonCallableBinding, PythonModuleBinding, PythonFileBinding)):
            return _execute_python_binding(tool, binding, arguments, artifact_mode, artifact_dir)
        if isinstance(binding, SubprocessBinding):
            return _execute_subprocess_binding(
                tool,
                binding,
                arguments,
                artifact_mode,
                artifact_dir,
            )
        if isinstance(binding, ArgparseCommandBinding):
            subprocess_binding = SubprocessBinding(
                argv=_render_argparse_argv(binding, arguments),
                result=SubprocessResultSpec(kind="stdout_text"),
            )
            return _execute_subprocess_binding(
                tool,
                subprocess_binding,
                arguments,
                artifact_mode,
                artifact_dir,
            )
        raise TypeError(f"Unsupported binding type: {type(binding)!r}")
    except SchemaValidationError as error:
        return _error_result(tool, arguments, artifact_mode, artifact_dir, str(error))
    except Exception as error:
        return _error_result(tool, arguments, artifact_mode, artifact_dir, str(error))


def _execute_python_binding(
    tool: ToolManifest,
    binding: PythonCallableBinding | PythonModuleBinding | PythonFileBinding,
    arguments: dict[str, Any],
    artifact_mode: str,
    artifact_dir: Path | None,
) -> ToolExecutionResult:
    """Execute a Python callable binding."""
    callable_obj = _resolve_python_callable(binding)
    invocation = {
        "kind": "python",
        "callable": tool.source.location or tool.name,
    }
    _write_invocation_record(artifact_dir, tool=tool, arguments=arguments, rendered=invocation)
    started_at = _utc_timestamp()
    started_monotonic = time.perf_counter()
    signature = inspect.signature(callable_obj)
    hints = get_type_hints(callable_obj, include_extras=True)
    coerced_arguments: dict[str, Any] = {}
    for parameter in signature.parameters.values():
        if parameter.name not in arguments:
            if parameter.default is inspect.Signature.empty:
                raise KeyError(parameter.name)
            continue
        coerced_arguments[parameter.name] = coerce_value(
            arguments[parameter.name],
            hints.get(parameter.name, parameter.annotation),
        )
    stdout_buffer = io.StringIO()
    stderr_buffer = io.StringIO()
    with contextlib.redirect_stdout(stdout_buffer), contextlib.redirect_stderr(stderr_buffer):
        if inspect.iscoroutinefunction(callable_obj):
            raw_result = asyncio.run(callable_obj(**coerced_arguments))
        else:
            raw_result = callable_obj(**coerced_arguments)
    ended_at = _utc_timestamp()
    duration_seconds = round(time.perf_counter() - started_monotonic, 6)
    stdout_text = stdout_buffer.getvalue()
    stderr_text = stderr_buffer.getvalue()
    normalized_result = _normalize_result(raw_result)
    execution_record = {
        "status": "ok",
        "startedAt": started_at,
        "endedAt": ended_at,
        "durationSeconds": duration_seconds,
        "stdoutBytes": len(stdout_text.encode("utf-8")),
        "stderrBytes": len(stderr_text.encode("utf-8")),
    }
    _write_stream_logs(artifact_dir, artifact_mode, stdout_text, stderr_text)
    _write_execution_record(artifact_dir, execution_record)
    _write_structured_result(artifact_dir, normalized_result.structured_content)
    return ToolExecutionResult(
        content=normalized_result.content,
        structured_content=normalized_result.structured_content,
        artifact_dir=artifact_dir,
        meta=_tool_meta(artifact_dir, execution_record),
    )


def _execute_subprocess_binding(
    tool: ToolManifest,
    binding: SubprocessBinding,
    arguments: dict[str, Any],
    artifact_mode: str,
    artifact_dir: Path | None,
) -> ToolExecutionResult:
    """Execute a manifest-driven subprocess binding."""
    if binding.timeout_seconds is not None and binding.timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be greater than zero.")
    if artifact_dir is None:
        with tempfile.TemporaryDirectory(prefix=f"mcpwrap-{tool.name}-") as temp_dir:
            return _run_subprocess_in_workspace(
                tool=tool,
                binding=binding,
                arguments=arguments,
                workspace=Path(temp_dir),
                artifact_mode=artifact_mode,
                retained_artifact_dir=None,
            )
    artifact_dir.mkdir(parents=True, exist_ok=True)
    if artifact_mode == "full":
        return _run_subprocess_in_workspace(
            tool=tool,
            binding=binding,
            arguments=arguments,
            workspace=artifact_dir,
            artifact_mode=artifact_mode,
            retained_artifact_dir=artifact_dir,
        )
    with tempfile.TemporaryDirectory(prefix=f"mcpwrap-{tool.name}-") as temp_dir:
        return _run_subprocess_in_workspace(
            tool=tool,
            binding=binding,
            arguments=arguments,
            workspace=Path(temp_dir),
            artifact_mode=artifact_mode,
            retained_artifact_dir=artifact_dir,
        )


def _run_subprocess_in_workspace(
    *,
    tool: ToolManifest,
    binding: SubprocessBinding,
    arguments: dict[str, Any],
    workspace: Path,
    artifact_mode: str,
    retained_artifact_dir: Path | None,
) -> ToolExecutionResult:
    """Run a subprocess binding inside a prepared working directory."""
    prepared = _prepare_subprocess_run(binding, arguments, workspace)
    invocation = {
        "kind": "subprocess",
        "argv": list(prepared.rendered_argv),
        "cwd": str(prepared.command_cwd),
        "env": prepared.rendered_env,
        "stdin": prepared.stdin_text,
        "files": prepared.rendered_files,
    }
    _write_invocation_record(
        retained_artifact_dir,
        tool=tool,
        arguments=arguments,
        rendered=invocation,
    )
    started_at = _utc_timestamp()
    started_monotonic = time.perf_counter()
    try:
        process = subprocess.run(
            prepared.rendered_argv,
            cwd=prepared.command_cwd,
            env={**os.environ, **prepared.rendered_env},
            input=prepared.stdin_text,
            capture_output=True,
            text=True,
            check=False,
            timeout=binding.timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        ended_at = _utc_timestamp()
        duration_seconds = round(time.perf_counter() - started_monotonic, 6)
        stdout_text = error.stdout if isinstance(error.stdout, str) else ""
        stderr_text = error.stderr if isinstance(error.stderr, str) else ""
        timeout_text = f"Subprocess timed out after {binding.timeout_seconds} seconds."
        _write_stream_logs(
            retained_artifact_dir,
            artifact_mode,
            stdout_text,
            stderr_text or timeout_text,
        )
        copied_outputs = _retain_output_paths(
            retained_artifact_dir,
            artifact_mode,
            prepared.command_cwd,
            binding.retained_paths,
            status="error",
        )
        execution_record = {
            "status": "timeout",
            "startedAt": started_at,
            "endedAt": ended_at,
            "durationSeconds": duration_seconds,
            "timedOut": True,
            "exitCode": None,
            "cwd": str(prepared.command_cwd),
            "argv": list(prepared.rendered_argv),
            "stdoutBytes": len(stdout_text.encode("utf-8")),
            "stderrBytes": len((stderr_text or timeout_text).encode("utf-8")),
            "retainedOutputs": copied_outputs,
        }
        _write_execution_record(retained_artifact_dir, execution_record)
        return ToolExecutionResult(
            content=(_text_block(timeout_text),),
            artifact_dir=retained_artifact_dir,
            is_error=True,
            meta=_tool_meta(retained_artifact_dir, execution_record),
        )
    ended_at = _utc_timestamp()
    duration_seconds = round(time.perf_counter() - started_monotonic, 6)
    _write_stream_logs(retained_artifact_dir, artifact_mode, process.stdout, process.stderr)
    copied_outputs = _retain_output_paths(
        retained_artifact_dir,
        artifact_mode,
        prepared.command_cwd,
        binding.retained_paths,
        status="success" if process.returncode == 0 else "error",
    )
    execution_record = {
        "status": "ok" if process.returncode == 0 else "error",
        "startedAt": started_at,
        "endedAt": ended_at,
        "durationSeconds": duration_seconds,
        "timedOut": False,
        "exitCode": process.returncode,
        "cwd": str(prepared.command_cwd),
        "argv": list(prepared.rendered_argv),
        "stdoutBytes": len(process.stdout.encode("utf-8")),
        "stderrBytes": len(process.stderr.encode("utf-8")),
        "retainedOutputs": copied_outputs,
    }
    if process.returncode != 0:
        _write_execution_record(retained_artifact_dir, execution_record)
        error_text = (
            process.stderr.strip() or process.stdout.strip() or "Subprocess execution failed."
        )
        return ToolExecutionResult(
            content=(_text_block(error_text),),
            artifact_dir=retained_artifact_dir,
            is_error=True,
            meta=_tool_meta(retained_artifact_dir, execution_record),
        )
    try:
        structured_content, content = _extract_subprocess_result(
            process.stdout,
            result_spec=binding.result,
            workspace=prepared.command_cwd,
        )
    except Exception as error:
        execution_record["status"] = "result_error"
        execution_record["resultExtractionError"] = str(error)
        _write_execution_record(retained_artifact_dir, execution_record)
        return ToolExecutionResult(
            content=(
                _text_block(
                    f"Subprocess completed successfully, but result extraction failed: {error}"
                ),
            ),
            artifact_dir=retained_artifact_dir,
            is_error=True,
            meta=_tool_meta(retained_artifact_dir, execution_record),
        )
    _write_execution_record(retained_artifact_dir, execution_record)
    _write_structured_result(retained_artifact_dir, structured_content)
    return ToolExecutionResult(
        content=content,
        structured_content=structured_content,
        artifact_dir=retained_artifact_dir,
        meta=_tool_meta(retained_artifact_dir, execution_record),
    )


def _prepare_subprocess_run(
    binding: SubprocessBinding,
    arguments: dict[str, Any],
    workspace: Path,
) -> PreparedSubprocessRun:
    """Render one subprocess binding into a concrete invocation."""
    rendered_files = _render_files(binding.files, arguments, workspace)
    rendered_argv = tuple(_render_template(item, arguments) for item in binding.argv)
    rendered_env = {
        key: _render_template(value, arguments) for key, value in (binding.env or {}).items()
    }
    stdin_text = (
        _render_template(binding.stdin_template, arguments)
        if binding.stdin_template is not None
        else None
    )
    command_cwd = workspace
    if binding.cwd is not None:
        rendered_cwd = Path(_render_template(binding.cwd, arguments))
        command_cwd = rendered_cwd if rendered_cwd.is_absolute() else workspace / rendered_cwd
        command_cwd.mkdir(parents=True, exist_ok=True)
    return PreparedSubprocessRun(
        rendered_argv=rendered_argv,
        rendered_env=rendered_env,
        stdin_text=stdin_text,
        command_cwd=command_cwd,
        rendered_files=rendered_files,
    )


def _render_files(
    templates: tuple[FileTemplate, ...],
    arguments: dict[str, Any],
    workspace: Path,
) -> list[str]:
    """Render configured input files into the working directory."""
    rendered_paths: list[str] = []
    for file_template in templates:
        output_path = workspace / file_template.path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            _render_template(file_template.template, arguments),
            encoding="utf-8",
        )
        rendered_paths.append(str(output_path))
    return rendered_paths


def _render_template(template: str, arguments: dict[str, Any]) -> str:
    """Render a deterministic string template with tool arguments."""
    return template.format_map(arguments)


def _render_argparse_argv(
    binding: ArgparseCommandBinding,
    arguments: dict[str, Any],
) -> tuple[str, ...]:
    """Translate validated tool arguments into a CLI argv sequence."""
    argv: list[str] = list(binding.command)
    for action in binding.actions:
        value = arguments.get(action.dest)
        if action.positional:
            if value is None:
                continue
            if isinstance(value, list):
                argv.extend(str(item) for item in value)
            else:
                argv.append(str(value))
            continue
        if action.action == "store_true":
            if value:
                argv.append(action.option_strings[0])
            continue
        if action.action == "store_false":
            if value is False:
                argv.append(action.option_strings[0])
            continue
        if value is None:
            continue
        argv.append(action.option_strings[0])
        if isinstance(value, list):
            argv.extend(str(item) for item in value)
        else:
            argv.append(str(value))
    return tuple(argv)


def _extract_subprocess_result(
    stdout_text: str,
    result_spec: SubprocessResultSpec,
    workspace: Path,
) -> tuple[dict[str, Any] | None, tuple[dict[str, str], ...]]:
    """Extract a normalized result from subprocess outputs."""
    if result_spec.kind == "stdout_json":
        structured = json.loads(stdout_text)
        return _object_structured_content(structured), (
            _text_block(json.dumps(structured, sort_keys=True)),
        )
    if result_spec.kind == "file_text":
        if result_spec.path is None:
            raise ValueError("file_text requires a result path.")
        text = (workspace / result_spec.path).read_text(encoding="utf-8")
        return None, (_text_block(text),)
    if result_spec.kind == "file_json":
        if result_spec.path is None:
            raise ValueError("file_json requires a result path.")
        structured = json.loads((workspace / result_spec.path).read_text(encoding="utf-8"))
        return _object_structured_content(structured), (
            _text_block(json.dumps(structured, sort_keys=True)),
        )
    if result_spec.kind == "file_bytes":
        if result_spec.path is None:
            raise ValueError("file_bytes requires a result path.")
        payload = base64.b64encode((workspace / result_spec.path).read_bytes()).decode("ascii")
        structured = {"path": result_spec.path, "contentBase64": payload}
        return structured, (_text_block(json.dumps(structured, sort_keys=True)),)
    if result_spec.kind == "directory_manifest":
        if result_spec.path is None:
            raise ValueError("directory_manifest requires a result path.")
        structured = _directory_manifest(workspace / result_spec.path, result_spec.path)
        return structured, (_text_block(json.dumps(structured, sort_keys=True)),)
    return None, (_text_block(stdout_text.rstrip("\n")),)


def _normalize_result(value: Any, artifact_dir: Path | None = None) -> ToolExecutionResult:
    """Normalize a Python return value into MCP-compatible content."""
    del artifact_dir
    try:
        structured = to_json_compatible(value)
    except TypeError:
        return ToolExecutionResult(content=(_text_block(str(value)),))
    if isinstance(structured, str):
        return ToolExecutionResult(content=(_text_block(structured),))
    return ToolExecutionResult(
        content=(_text_block(json.dumps(structured, sort_keys=True)),),
        structured_content=_object_structured_content(structured),
    )


def _resolve_python_callable(
    binding: PythonCallableBinding | PythonModuleBinding | PythonFileBinding,
) -> Callable[..., Any]:
    """Resolve one Python binding into an executable callable object."""
    if isinstance(binding, PythonCallableBinding):
        return binding.callable_obj
    if isinstance(binding, PythonModuleBinding):
        importlib.invalidate_caches()
        module = importlib.import_module(binding.module_name)
        if binding.module_name in sys.modules:
            module = importlib.reload(module)
        return cast(Callable[..., Any], resolve_qualname(module, binding.qualname))
    module = load_module_from_path(Path(binding.file_path), fresh=True)
    return cast(Callable[..., Any], resolve_qualname(module, binding.qualname))


def _retain_output_paths(
    artifact_dir: Path | None,
    artifact_mode: str,
    command_cwd: Path,
    retained_paths: tuple[RetainedPathSpec, ...],
    *,
    status: str,
) -> list[dict[str, Any]]:
    """Copy configured output paths into retained artifacts and return metadata."""
    if artifact_dir is None:
        return []
    retained: list[dict[str, Any]] = []
    for spec in retained_paths:
        if spec.when not in {"always", status}:
            continue
        source_path = command_cwd / spec.path
        if not source_path.exists():
            if spec.optional:
                continue
            raise FileNotFoundError(f"Configured retained path is missing: {source_path}")
        kind = _path_kind(source_path)
        if spec.kind != "auto" and kind != spec.kind:
            raise ValueError(
                f"Retained path {source_path} expected kind {spec.kind!r}, found {kind!r}."
            )
        destination = artifact_dir / "outputs" / spec.path
        if artifact_mode == "full" and _is_relative_to(source_path, artifact_dir):
            retained.append(_artifact_record_for_path(source_path, artifact_dir))
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source_path.is_dir():
            if destination.exists():
                shutil.rmtree(destination)
            shutil.copytree(source_path, destination)
        else:
            shutil.copy2(source_path, destination)
        retained.append(_artifact_record_for_path(destination, artifact_dir))
    return retained


def _path_kind(path: Path) -> str:
    """Return the deterministic kind for a filesystem path."""
    return "directory" if path.is_dir() else "file"


def _is_relative_to(path: Path, root: Path) -> bool:
    """Return whether ``path`` is contained within ``root``."""
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _directory_manifest(path: Path, reported_path: str) -> dict[str, Any]:
    """Build a deterministic directory listing payload."""
    if not path.is_dir():
        raise NotADirectoryError(path)
    entries = [
        {
            "path": str(child.relative_to(path)),
            "kind": "directory" if child.is_dir() else "file",
            "size": child.stat().st_size if child.is_file() else None,
        }
        for child in sorted(path.rglob("*"))
    ]
    return {"path": reported_path, "entries": entries}


def _text_block(text: str) -> dict[str, str]:
    """Build one MCP text content block."""
    return {"type": "text", "text": text}


def _object_structured_content(value: Any) -> dict[str, Any] | None:
    """Normalize structured content to an MCP-compatible object payload."""
    if isinstance(value, dict):
        return value
    return None


def _create_artifact_dir(manifest: Manifest, tool_name: str) -> Path | None:
    """Create an artifact directory based on the manifest policy."""
    if manifest.artifact_policy.mode == "none":
        return None
    root_dir = manifest.artifact_policy.root_dir
    root_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    artifact_dir = root_dir / f"{tool_name}-{timestamp}-{uuid4().hex[:8]}"
    artifact_dir.mkdir(parents=True, exist_ok=False)
    return artifact_dir


def _write_invocation_record(
    artifact_dir: Path | None,
    *,
    tool: ToolManifest,
    arguments: dict[str, Any],
    rendered: dict[str, Any],
) -> None:
    """Persist the pre-execution invocation record when retention is enabled."""
    if artifact_dir is None:
        return
    invocation = {
        "tool": tool.name,
        "description": tool.description,
        "arguments": arguments,
        "rendered": rendered,
    }
    (artifact_dir / "invocation.json").write_text(
        json.dumps(invocation, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _write_stream_logs(
    artifact_dir: Path | None,
    artifact_mode: str,
    stdout_text: str,
    stderr_text: str,
) -> None:
    """Persist stdout and stderr streams when retention is enabled."""
    if artifact_dir is None or artifact_mode == "none":
        return
    (artifact_dir / "stdout.txt").write_text(stdout_text, encoding="utf-8")
    (artifact_dir / "stderr.txt").write_text(stderr_text, encoding="utf-8")


def _write_structured_result(
    artifact_dir: Path | None,
    structured_content: dict[str, Any] | None,
) -> None:
    """Persist structured tool output when it exists."""
    if artifact_dir is None or structured_content is None:
        return
    (artifact_dir / "result.json").write_text(
        json.dumps(structured_content, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _write_execution_record(
    artifact_dir: Path | None,
    execution_record: dict[str, Any],
) -> None:
    """Persist the post-execution record when retention is enabled."""
    if artifact_dir is None:
        return
    (artifact_dir / "execution.json").write_text(
        json.dumps(execution_record, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _tool_meta(
    artifact_dir: Path | None,
    execution_record: dict[str, Any],
) -> dict[str, Any]:
    """Build the MCP ``_meta`` payload returned alongside tool results."""
    meta: dict[str, Any] = {"mcpwrap/execution": execution_record}
    if artifact_dir is not None:
        meta["mcpwrap/artifactDir"] = str(artifact_dir)
        meta["mcpwrap/artifacts"] = _artifact_records(artifact_dir)
    return meta


def _artifact_records(artifact_dir: Path) -> list[dict[str, Any]]:
    """Return a deterministic listing of retained artifacts."""
    records: list[dict[str, Any]] = []
    for path in sorted(artifact_dir.rglob("*")):
        if path.is_dir():
            continue
        records.append(_artifact_record_for_path(path, artifact_dir))
    return records


def _artifact_record_for_path(path: Path, artifact_dir: Path) -> dict[str, Any]:
    """Return one serialized artifact record for a retained path."""
    return {
        "path": str(path.relative_to(artifact_dir)),
        "kind": _path_kind(path),
        "size": path.stat().st_size,
    }


def _error_result(
    tool: ToolManifest,
    arguments: dict[str, Any],
    artifact_mode: str,
    artifact_dir: Path | None,
    error_text: str,
) -> ToolExecutionResult:
    """Build a tool-level error result and capture its artifacts."""
    _write_invocation_record(
        artifact_dir,
        tool=tool,
        arguments=arguments,
        rendered={"kind": "error"},
    )
    _write_stream_logs(artifact_dir, artifact_mode, "", error_text)
    execution_record = {
        "status": "error",
        "startedAt": _utc_timestamp(),
        "endedAt": _utc_timestamp(),
        "durationSeconds": 0.0,
        "timedOut": False,
        "exitCode": None,
        "error": error_text,
    }
    _write_execution_record(artifact_dir, execution_record)
    return ToolExecutionResult(
        content=(_text_block(error_text),),
        artifact_dir=artifact_dir,
        is_error=True,
        meta=_tool_meta(artifact_dir, execution_record),
    )


def _utc_timestamp() -> str:
    """Return the current UTC timestamp formatted for persisted records."""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")

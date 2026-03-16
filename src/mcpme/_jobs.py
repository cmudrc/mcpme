"""Deterministic background job management for long-running subprocess tools."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from .execution import (
    SubprocessBinding,
    _extract_subprocess_result,
    _prepare_subprocess_run,
    _retain_output_paths,
    _tool_meta,
    _utc_timestamp,
    _write_execution_record,
    _write_invocation_record,
    _write_stream_logs,
    _write_structured_result,
)
from .manifest import Manifest, ToolManifest
from .schema import validate_value


@dataclass(slots=True)
class _ManagedJob:
    """Track one live subprocess job managed by the current runtime."""

    job_id: str
    tool: ToolManifest
    binding: SubprocessBinding
    arguments: dict[str, Any]
    artifact_dir: Path
    workspace: Path
    prepared: Any
    process: subprocess.Popen[str]
    artifact_mode: str
    started_at: str
    started_monotonic: float


class JobManager:
    """Manage long-running subprocess tool jobs backed by local artifact records."""

    def __init__(self, manifest: Manifest) -> None:
        """Create a job manager rooted at the manifest artifact directory."""
        self._manifest = manifest
        self._jobs_root = manifest.artifact_policy.root_dir / "jobs"
        self._jobs_root.mkdir(parents=True, exist_ok=True)
        self._active_jobs: dict[str, _ManagedJob] = {}
        self._lock = threading.Lock()
        self._hydrate_existing_records()

    def start(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Start one subprocess tool as a managed background job."""
        tool = self._manifest.get_tool(name)
        validate_value(arguments, tool.input_schema)
        binding = self._manifest.get_binding(name)
        if not isinstance(binding, SubprocessBinding):
            raise ValueError("Background jobs are currently supported only for subprocess tools.")
        if binding.timeout_seconds is not None and binding.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero.")

        job_id = uuid4().hex[:12]
        artifact_dir = self._jobs_root / job_id
        artifact_dir.mkdir(parents=True, exist_ok=False)
        workspace = artifact_dir / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        prepared = _prepare_subprocess_run(binding, arguments, workspace)
        _write_invocation_record(
            artifact_dir,
            tool=tool,
            arguments=arguments,
            rendered={
                "kind": "subprocess",
                "argv": list(prepared.rendered_argv),
                "cwd": str(prepared.command_cwd),
                "env": prepared.rendered_env,
                "stdin": prepared.stdin_text,
                "files": prepared.rendered_files,
            },
        )
        stdout_file = (artifact_dir / "stdout.txt").open("w", encoding="utf-8")
        stderr_file = (artifact_dir / "stderr.txt").open("w", encoding="utf-8")
        process = subprocess.Popen(
            prepared.rendered_argv,
            cwd=prepared.command_cwd,
            env={**os.environ, **prepared.rendered_env},
            stdin=subprocess.PIPE if prepared.stdin_text is not None else None,
            stdout=stdout_file,
            stderr=stderr_file,
            text=True,
        )
        if prepared.stdin_text is not None and process.stdin is not None:
            process.stdin.write(prepared.stdin_text)
            process.stdin.close()
        started_at = _utc_timestamp()
        managed = _ManagedJob(
            job_id=job_id,
            tool=tool,
            binding=binding,
            arguments=arguments,
            artifact_dir=artifact_dir,
            workspace=workspace,
            prepared=prepared,
            process=process,
            artifact_mode=(
                self._manifest.artifact_policy.mode
                if self._manifest.artifact_policy.mode != "none"
                else "summary"
            ),
            started_at=started_at,
            started_monotonic=time.perf_counter(),
        )
        initial_record = {
            "jobId": job_id,
            "tool": tool.name,
            "status": "running",
            "artifactDir": str(artifact_dir),
            "workspace": str(workspace),
            "pid": process.pid,
            "argv": list(prepared.rendered_argv),
            "cwd": str(prepared.command_cwd),
            "timeoutSeconds": binding.timeout_seconds,
            "startedAt": started_at,
            "updatedAt": started_at,
            "exitCode": None,
            "timedOut": False,
            "cancelRequested": False,
        }
        self._write_job_record(job_id, initial_record)
        with self._lock:
            self._active_jobs[job_id] = managed
        monitor = threading.Thread(
            target=self._monitor_job,
            args=(managed,),
            daemon=True,
            name=f"mcpme-job-{job_id}",
        )
        monitor.start()
        return self.get(job_id)

    def list_jobs(self) -> list[dict[str, Any]]:
        """Return all known job records sorted by recency."""
        jobs = [self.get(job_dir.name) for job_dir in self._jobs_root.iterdir() if job_dir.is_dir()]
        return sorted(jobs, key=lambda item: item.get("startedAt", ""), reverse=True)

    def get(self, job_id: str) -> dict[str, Any]:
        """Return one persisted job record."""
        record = self._read_job_record(job_id)
        with self._lock:
            managed = self._active_jobs.get(job_id)
        if (
            managed is None
            and record.get("status") == "running"
            and isinstance(record.get("pid"), int)
        ):
            refreshed_record = self._read_job_record(job_id)
            refreshed_pid = refreshed_record.get("pid")
            if refreshed_record.get("status") != "running":
                return refreshed_record
            if isinstance(refreshed_pid, int) and not _pid_exists(refreshed_pid):
                refreshed_record["status"] = "lost"
                refreshed_record["updatedAt"] = _utc_timestamp()
                self._write_job_record(job_id, refreshed_record)
                return refreshed_record
        return record

    def cancel(self, job_id: str) -> dict[str, Any]:
        """Request cancellation for one managed or persisted job."""
        record = self.get(job_id)
        pid = record.get("pid")
        record["cancelRequested"] = True
        record["updatedAt"] = _utc_timestamp()
        self._write_job_record(job_id, record)
        with self._lock:
            managed = self._active_jobs.get(job_id)
        if managed is not None:
            managed.process.terminate()
            return self.get(job_id)
        if isinstance(pid, int) and _pid_exists(pid):
            os.kill(pid, signal.SIGTERM)
        return self.get(job_id)

    def tail(self, job_id: str, *, stream: str = "stdout", lines: int = 100) -> dict[str, Any]:
        """Return the last few lines of one job stream."""
        if stream not in {"stdout", "stderr"}:
            raise ValueError("stream must be 'stdout' or 'stderr'.")
        artifact_dir = self._job_dir(job_id)
        path = artifact_dir / f"{stream}.txt"
        return {
            "jobId": job_id,
            "stream": stream,
            "lines": _tail_text_file(path, lines),
        }

    def _monitor_job(self, managed: _ManagedJob) -> None:
        """Wait for one background job and finalize its persisted record."""
        timed_out = False
        returncode: int | None
        try:
            returncode = managed.process.wait(timeout=managed.binding.timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            managed.process.terminate()
            try:
                managed.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                managed.process.kill()
                managed.process.wait()
            returncode = None
        ended_at = _utc_timestamp()
        duration_seconds = round(time.perf_counter() - managed.started_monotonic, 6)
        stdout_text = _safe_read_text(managed.artifact_dir / "stdout.txt")
        stderr_text = _safe_read_text(managed.artifact_dir / "stderr.txt")
        copied_outputs = _retain_output_paths(
            managed.artifact_dir,
            managed.artifact_mode,
            managed.prepared.command_cwd,
            managed.binding.retained_paths,
            status="error" if timed_out or returncode not in (0, None) else "success",
        )
        record = self._read_job_record(managed.job_id)
        cancel_requested = bool(record.get("cancelRequested"))
        if timed_out:
            status = "timeout"
            error_text = f"Subprocess timed out after {managed.binding.timeout_seconds} seconds."
            if not stderr_text:
                _write_stream_logs(
                    managed.artifact_dir,
                    managed.artifact_mode,
                    stdout_text,
                    error_text,
                )
                stderr_text = error_text
            structured_content = None
        elif cancel_requested:
            status = "cancelled"
            error_text = stderr_text.strip() or stdout_text.strip() or "Job cancelled."
            structured_content = None
        elif returncode not in (0, None):
            status = "error"
            error_text = (
                stderr_text.strip() or stdout_text.strip() or "Subprocess execution failed."
            )
            structured_content = None
        else:
            error_text = ""
            try:
                structured_content, _ = _extract_subprocess_result(
                    stdout_text,
                    result_spec=managed.binding.result,
                    workspace=managed.prepared.command_cwd,
                )
                _write_structured_result(managed.artifact_dir, structured_content)
                status = "completed"
            except Exception as error:
                structured_content = None
                status = "result_error"
                error_text = str(error)
        execution_record = {
            "status": status,
            "startedAt": managed.started_at,
            "endedAt": ended_at,
            "durationSeconds": duration_seconds,
            "timedOut": timed_out,
            "exitCode": returncode,
            "cwd": str(managed.prepared.command_cwd),
            "argv": list(managed.prepared.rendered_argv),
            "stdoutBytes": len(stdout_text.encode("utf-8")),
            "stderrBytes": len(stderr_text.encode("utf-8")),
            "retainedOutputs": copied_outputs,
        }
        if error_text:
            execution_record["error"] = error_text
        _write_execution_record(managed.artifact_dir, execution_record)
        record.update(
            {
                "status": status,
                "updatedAt": ended_at,
                "endedAt": ended_at,
                "exitCode": returncode,
                "timedOut": timed_out,
                "error": error_text or None,
                "result": structured_content,
                "meta": _tool_meta(managed.artifact_dir, execution_record),
            }
        )
        self._write_job_record(managed.job_id, record)
        with self._lock:
            self._active_jobs.pop(managed.job_id, None)

    def _hydrate_existing_records(self) -> None:
        """Update persisted job records from prior runtime sessions."""
        for job_dir in self._jobs_root.iterdir():
            if not job_dir.is_dir():
                continue
            record_path = job_dir / "job.json"
            if not record_path.exists():
                continue
            record = _read_json_file(record_path)
            if record.get("status") == "running":
                pid = record.get("pid")
                if not isinstance(pid, int) or not _pid_exists(pid):
                    record["status"] = "lost"
                    record["updatedAt"] = _utc_timestamp()
                    _write_json_file(record_path, record)

    def _job_dir(self, job_id: str) -> Path:
        """Return the persisted artifact directory for one job ID."""
        job_dir = self._jobs_root / job_id
        if not job_dir.exists():
            raise KeyError(job_id)
        return job_dir

    def _read_job_record(self, job_id: str) -> dict[str, Any]:
        """Read one persisted job record from disk."""
        job_dir = self._job_dir(job_id)
        return _read_json_file(job_dir / "job.json")

    def _write_job_record(self, job_id: str, record: dict[str, Any]) -> None:
        """Persist one job record to disk."""
        job_dir = self._jobs_root / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        _write_json_file(job_dir / "job.json", record)


def _safe_read_text(path: Path) -> str:
    """Read a text file when it exists, returning an empty string otherwise."""
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _read_json_file(
    path: Path,
    *,
    attempts: int = 5,
    delay_seconds: float = 0.01,
) -> dict[str, Any]:
    """Read one JSON mapping from disk with a small retry budget.

    Job records are polled while background monitor threads update them. The
    write path uses atomic replacement, but a bounded retry keeps reads robust
    against pre-existing partial files from older runs or interrupted writes.

    Args:
        path: JSON file path to load.
        attempts: Maximum read attempts before surfacing the decode failure.
        delay_seconds: Sleep duration between attempts.

    Returns:
        Parsed JSON object.

    Raises:
        json.JSONDecodeError: If the file never contains valid JSON.
    """
    last_error: json.JSONDecodeError | None = None
    for attempt in range(1, max(1, attempts) + 1):
        text = path.read_text(encoding="utf-8")
        try:
            loaded = json.loads(text)
        except json.JSONDecodeError as error:
            last_error = error
            if attempt == attempts:
                raise
            time.sleep(delay_seconds)
            continue
        if isinstance(loaded, dict):
            return loaded
        raise ValueError(f"{path}: job record must contain a JSON object.")
    assert last_error is not None
    raise last_error


def _write_json_file(path: Path, payload: dict[str, Any]) -> None:
    """Write one JSON mapping to disk atomically.

    Args:
        path: Destination JSON path.
        payload: Mapping to serialize.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
    temp_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temp_path.replace(path)


def _tail_text_file(path: Path, lines: int) -> str:
    """Return the last ``lines`` of a text file."""
    if not path.exists():
        return ""
    with path.open(encoding="utf-8") as handle:
        return "".join(deque(handle, maxlen=max(1, lines)))


def _pid_exists(pid: int) -> bool:
    """Return whether a process ID is still alive on the local machine."""
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True

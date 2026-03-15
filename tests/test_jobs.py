"""Tests for deterministic background job management."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from mcpme import build_manifest
from mcpme._jobs import JobManager, _pid_exists, _tail_text_file
from mcpme.execution import PythonCallableBinding, SubprocessBinding
from mcpme.manifest import ArtifactPolicy, Manifest, SourceReference, ToolManifest


def test_job_manager_supports_completion_cancel_and_tail(tmp_path: Path) -> None:
    """Background jobs should persist records, logs, and cancellation status."""

    script_path = tmp_path / "sleepy.py"
    script_path.write_text(
        "import sys\n"
        "import time\n\n"
        "delay = float(sys.argv[1])\n"
        "payload = sys.stdin.read().strip()\n"
        "print(f'start:{payload}', flush=True)\n"
        "time.sleep(delay)\n"
        "print(f'done:{payload}', flush=True)\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "mcpme.toml"
    config_path.write_text(
        f"""
[tool.mcpme]
artifact_root = "{(tmp_path / "artifacts").as_posix()}"

[[tool.mcpme.subprocess]]
name = "sleepy"
description = "Run slowly."
argv = ["{sys.executable}", "{script_path.as_posix()}", "{{delay}}"]
stdin_template = "{{message}}"
result_kind = "stdout_text"
timeout_seconds = 1.0

[tool.mcpme.subprocess.input_schema]
type = "object"
required = ["message", "delay"]

[tool.mcpme.subprocess.input_schema.properties.message]
type = "string"

[tool.mcpme.subprocess.input_schema.properties.delay]
type = "number"
""".strip(),
        encoding="utf-8",
    )

    manager = JobManager(build_manifest(config_path=config_path))
    completed = manager.start("sleepy", {"message": "mesh", "delay": 0.05})
    for _ in range(50):
        record = manager.get(completed["jobId"])
        if record["status"] == "completed":
            break
        time.sleep(0.02)
    assert record["status"] == "completed"
    assert "done:mesh" in manager.tail(completed["jobId"])["lines"]

    cancelled = manager.start("sleepy", {"message": "cancel", "delay": 0.5})
    manager.cancel(cancelled["jobId"])
    for _ in range(50):
        record = manager.get(cancelled["jobId"])
        if record["status"] == "cancelled":
            break
        time.sleep(0.02)
    assert record["status"] == "cancelled"
    assert any(job["jobId"] == completed["jobId"] for job in manager.list_jobs())


def test_job_manager_handles_edge_records_and_validation(tmp_path: Path) -> None:
    """Hydration, invalid streams, and bad job bindings should fail clearly."""

    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    ghost_dir = artifact_root / "jobs" / "ghost"
    ghost_dir.mkdir(parents=True)
    (ghost_dir / "job.json").write_text(
        json.dumps(
            {
                "jobId": "ghost",
                "tool": "ghost_tool",
                "status": "running",
                "pid": 999999,
                "startedAt": "2026-01-01T00:00:00Z",
                "updatedAt": "2026-01-01T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    manifest = Manifest(
        tools=(
            ToolManifest(
                name="ghost_tool",
                description="Ghost job.",
                input_schema={"type": "object", "properties": {}},
                source=SourceReference(kind="callable", target="ghost_tool"),
                binding_kind="python",
            ),
        ),
        artifact_policy=ArtifactPolicy(root_dir=artifact_root),
        runtime_bindings={"ghost_tool": PythonCallableBinding(lambda: None)},
    )
    manager = JobManager(manifest)
    assert manager.get("ghost")["status"] == "lost"

    late_dir = artifact_root / "jobs" / "late_ghost"
    late_dir.mkdir(parents=True)
    (late_dir / "job.json").write_text(
        json.dumps(
            {
                "jobId": "late_ghost",
                "tool": "ghost_tool",
                "status": "running",
                "pid": 999998,
                "startedAt": "2026-01-01T00:00:00Z",
                "updatedAt": "2026-01-01T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    assert manager.get("late_ghost")["status"] == "lost"

    assert _tail_text_file(ghost_dir / "missing.txt", 10) == ""
    assert _pid_exists(999999999) is False

    with pytest.raises(ValueError):
        manager.tail("ghost", stream="bad")

    bad_manifest = Manifest(
        tools=(
            ToolManifest(
                name="bad_timeout",
                description="Bad timeout job.",
                input_schema={"type": "object", "properties": {}},
                source=SourceReference(kind="subprocess", target="bad_timeout"),
                binding_kind="subprocess",
            ),
        ),
        artifact_policy=ArtifactPolicy(root_dir=tmp_path / "bad_artifacts"),
        runtime_bindings={
            "bad_timeout": SubprocessBinding(
                argv=(sys.executable, "-c", "print('hi')"),
                timeout_seconds=0,
            )
        },
    )
    with pytest.raises(ValueError):
        JobManager(bad_manifest).start("bad_timeout", {})

    with pytest.raises(ValueError):
        manager.start("ghost_tool", {})

    live_process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(5)"])
    try:
        live_dir = artifact_root / "jobs" / "live"
        live_dir.mkdir(parents=True)
        (live_dir / "job.json").write_text(
            json.dumps(
                {
                    "jobId": "live",
                    "tool": "ghost_tool",
                    "status": "running",
                    "pid": live_process.pid,
                    "startedAt": "2026-01-01T00:00:00Z",
                    "updatedAt": "2026-01-01T00:00:00Z",
                }
            ),
            encoding="utf-8",
        )
        assert manager.cancel("live")["cancelRequested"] is True
    finally:
        live_process.wait(timeout=5)


def test_job_manager_records_timeouts_and_result_errors(tmp_path: Path) -> None:
    """Timeouts and result extraction failures should persist as explicit statuses."""

    sleepy_script = tmp_path / "timeout.py"
    sleepy_script.write_text(
        "import sys\n"
        "import time\n\n"
        "time.sleep(float(sys.argv[1]))\n"
        "print('finished', flush=True)\n",
        encoding="utf-8",
    )
    timeout_config = tmp_path / "timeout.toml"
    timeout_config.write_text(
        f"""
[tool.mcpme]
artifact_root = "{(tmp_path / "timeout_artifacts").as_posix()}"

[[tool.mcpme.subprocess]]
name = "timeout_job"
description = "Timeout job."
argv = ["{sys.executable}", "{sleepy_script.as_posix()}", "{{delay}}"]
result_kind = "stdout_text"
timeout_seconds = 0.05

[tool.mcpme.subprocess.input_schema]
type = "object"
required = ["delay"]

[tool.mcpme.subprocess.input_schema.properties.delay]
type = "number"
""".strip(),
        encoding="utf-8",
    )
    timeout_manager = JobManager(build_manifest(config_path=timeout_config))
    timeout_job = timeout_manager.start("timeout_job", {"delay": 0.2})
    for _ in range(50):
        record = timeout_manager.get(timeout_job["jobId"])
        if record["status"] == "timeout":
            break
        time.sleep(0.02)
    assert record["status"] == "timeout"

    result_script = tmp_path / "result_error.py"
    result_script.write_text("print('finished', flush=True)\n", encoding="utf-8")
    result_config = tmp_path / "result_error.toml"
    result_config.write_text(
        f"""
[tool.mcpme]
artifact_root = "{(tmp_path / "result_artifacts").as_posix()}"

[[tool.mcpme.subprocess]]
name = "result_error"
description = "Missing result file."
argv = ["{sys.executable}", "{result_script.as_posix()}"]
result_kind = "file_json"
result_path = "missing.json"
input_schema = {{ type = "object", properties = {{ }}, required = [] }}
""".strip(),
        encoding="utf-8",
    )
    result_manager = JobManager(build_manifest(config_path=result_config))
    result_job = result_manager.start("result_error", {})
    for _ in range(50):
        record = result_manager.get(result_job["jobId"])
        if record["status"] == "result_error":
            break
        time.sleep(0.02)
    assert record["status"] == "result_error"

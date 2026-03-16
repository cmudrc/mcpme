"""Tests for configuration loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from mcpme.config import load_config


def test_load_config_discovers_pyproject_and_parses_overrides(
    tmp_path: Path, monkeypatch: object
) -> None:
    """Embedded project config should load targets, overrides, and artifact policy."""

    target_file = tmp_path / "tools.py"
    target_file.write_text(
        """def run_job(job_name: str) -> str:\n"""
        '''    """Run a job.\n\n'''
        """    :param job_name: Job label.\n"""
        """    :returns: Job label.\n"""
        '''    """\n'''
        """    return job_name\n""",
        encoding="utf-8",
    )
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        f"""
[tool.mcpme]
targets = ["{target_file.as_posix()}"]
artifact_mode = "summary"
artifact_root = "artifacts"

[tool.mcpme.tool.run_job]
title = "Run Job"
read_only = true
""".strip(),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    config = load_config()

    assert config.targets == (str(target_file),)
    assert config.artifact_policy.mode == "summary"
    assert config.artifact_policy.root_dir == tmp_path / "artifacts"
    assert config.overrides["run_job"].title == "Run Job"
    assert config.overrides["run_job"].annotations.read_only is True


def test_load_config_supports_top_level_mcpme_table(tmp_path: Path) -> None:
    """Standalone config files may use a top-level ``[mcpme]`` table."""

    config_path = tmp_path / "mcpme.toml"
    config_path.write_text(
        """
[mcpme]
artifact_mode = "none"
""".strip(),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.artifact_policy.mode == "none"


def test_load_config_rejects_invalid_artifact_mode(tmp_path: Path) -> None:
    """Artifact mode should be validated eagerly."""

    config_path = tmp_path / "mcpme.toml"
    config_path.write_text(
        """
[mcpme]
artifact_mode = "mystery"
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        load_config(config_path)

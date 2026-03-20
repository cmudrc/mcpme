"""Tests for execution helper internals."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from mcpcraft.execution import (
    _directory_manifest,
    _extract_subprocess_result,
    _object_structured_content,
    _retain_output_paths,
)
from mcpcraft.manifest import RetainedPathSpec, SubprocessResultSpec


def test_execution_helper_extractors_and_retained_paths_cover_edge_cases(
    tmp_path: Path,
) -> None:
    """Internal subprocess helpers should cover binary, directory, and retention branches."""

    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    (artifact_dir / "out.txt").write_text("ok", encoding="utf-8")
    retained = _retain_output_paths(
        artifact_dir,
        "full",
        artifact_dir,
        (RetainedPathSpec(path="out.txt"),),
        status="success",
    )
    assert retained[0]["path"] == "out.txt"
    assert (
        _retain_output_paths(
            artifact_dir,
            "summary",
            tmp_path,
            (RetainedPathSpec(path="missing.txt", optional=True),),
            status="success",
        )
        == []
    )

    output_dir = tmp_path / "reports"
    output_dir.mkdir()
    (output_dir / "summary.txt").write_text("report", encoding="utf-8")
    with pytest.raises(ValueError):
        _retain_output_paths(
            artifact_dir,
            "summary",
            tmp_path,
            (RetainedPathSpec(path="reports", kind="file"),),
            status="success",
        )

    binary_path = tmp_path / "report.bin"
    binary_path.write_bytes(b"XYZ")
    binary_result, _ = _extract_subprocess_result(
        "",
        SubprocessResultSpec(kind="file_bytes", path="report.bin"),
        tmp_path,
    )
    assert binary_result == {
        "path": "report.bin",
        "contentBase64": base64.b64encode(b"XYZ").decode("ascii"),
    }

    directory_result, _ = _extract_subprocess_result(
        "",
        SubprocessResultSpec(kind="directory_manifest", path="reports"),
        tmp_path,
    )
    assert directory_result["entries"][0]["path"] == "summary.txt"

    with pytest.raises(ValueError):
        _extract_subprocess_result("", SubprocessResultSpec(kind="file_text"), tmp_path)
    with pytest.raises(NotADirectoryError):
        _directory_manifest(binary_path, "report.bin")

    assert _object_structured_content([1, 2, 3]) is None

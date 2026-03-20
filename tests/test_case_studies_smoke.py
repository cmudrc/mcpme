"""Smoke tests for the checked-in real-world example scripts."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SUPPORT_REQUIREMENTS = {
    "su2_cli": (
        REPO_ROOT / "examples" / "support" / "real_world" / "su2_cli" / "commands" / "su2_cfd.sh",
        REPO_ROOT
        / "examples"
        / "support"
        / "real_world"
        / "su2_cli"
        / "commands"
        / "scaffold_su2_cli.sh",
    ),
    "pycycle_mpcycle": (
        REPO_ROOT
        / "examples"
        / "support"
        / "real_world"
        / "pycycle_mpcycle"
        / "commands"
        / "scaffold_pycycle_mpcycle.sh",
    ),
    "tigl_cpacs": (
        REPO_ROOT
        / "examples"
        / "support"
        / "real_world"
        / "tigl_cpacs"
        / "commands"
        / "scaffold_tigl_cpacs.sh",
        REPO_ROOT
        / "examples"
        / "support"
        / "real_world"
        / "tigl_cpacs"
        / "tigl_support"
        / "__init__.py",
        REPO_ROOT
        / "examples"
        / "support"
        / "real_world"
        / "tigl_cpacs"
        / "tigl_support"
        / "core.py",
        REPO_ROOT
        / "examples"
        / "support"
        / "real_world"
        / "tigl_cpacs"
        / "fixtures"
        / "CPACS_30_D150.xml",
    ),
}


@pytest.mark.parametrize(
    ("case_id", "expected_pass_fragment", "expected_skip_fragment"),
    [
        ("su2_cli", "run_su2_cfd", "SU2_CFD"),
        ("pycycle_mpcycle", "pyc_add_cycle_param", "pycycle.api"),
        ("tigl_cpacs", "open_cpacs_summary", "TiGL/TiXI"),
    ],
)
def test_real_world_example_scripts_run_successfully(
    case_id: str,
    expected_pass_fragment: str,
    expected_skip_fragment: str,
) -> None:
    """Each real-world example should ingest first and then use deterministic artifacts."""
    for required_path in SUPPORT_REQUIREMENTS[case_id]:
        assert required_path.exists(), f"Missing checked-in support input: {required_path}"

    artifact_root = REPO_ROOT / "artifacts" / "examples" / "real_world" / case_id
    shutil.rmtree(artifact_root, ignore_errors=True)

    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT / "src")

    ingest_completed = subprocess.run(
        [sys.executable, f"examples/real_world/{case_id}/ingest.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert ingest_completed.returncode == 0, ingest_completed.stderr

    ingest_payload = json.loads(ingest_completed.stdout)
    assert ingest_payload["case_study"] == case_id
    assert ingest_payload["phase"] == "ingest"
    assert ingest_payload["status"] in {"passed", "skipped_unavailable"}

    if ingest_payload["status"] == "passed":
        generated_facade = Path(str(ingest_payload["artifacts"]["generated_facade"]))
        scaffold_report = Path(str(ingest_payload["artifacts"]["scaffold_report"]))
        assert generated_facade.exists(), f"Missing generated facade artifact: {generated_facade}"
        assert scaffold_report.exists(), f"Missing scaffold report artifact: {scaffold_report}"

    use_completed = subprocess.run(
        [sys.executable, f"examples/real_world/{case_id}/use.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert use_completed.returncode == 0, use_completed.stderr

    use_payload = json.loads(use_completed.stdout)
    assert use_payload["case_study"] == case_id
    assert use_payload["phase"] == "use"
    assert use_payload["status"] == ingest_payload["status"]

    if ingest_payload["status"] == "passed":
        assert "report" in ingest_payload
        assert "artifacts" in ingest_payload
        assert "reason" not in ingest_payload
        rendered = json.dumps(use_payload, sort_keys=True)
        assert expected_pass_fragment in rendered
        assert "artifacts" in use_payload
        assert "report" in use_payload
        assert "result" in use_payload
        assert "reason" not in use_payload
        return

    assert expected_skip_fragment in ingest_payload["reason"]
    assert expected_skip_fragment in use_payload["reason"]
    assert "report" not in use_payload
    assert "result" not in use_payload

"""Smoke tests for the checked-in case-study scripts."""

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
    "su2_cli.py": (
        REPO_ROOT / "case_studies" / "support" / "su2_cli" / "commands" / "su2_cfd.sh",
        REPO_ROOT / "case_studies" / "support" / "su2_cli" / "commands" / "scaffold_su2_cli.sh",
    ),
    "pycycle_mpcycle.py": (
        REPO_ROOT
        / "case_studies"
        / "support"
        / "pycycle_mpcycle"
        / "commands"
        / "scaffold_pycycle_mpcycle.sh",
    ),
    "tigl_cpacs.py": (
        REPO_ROOT
        / "case_studies"
        / "support"
        / "tigl_cpacs"
        / "commands"
        / "scaffold_tigl_cpacs.sh",
        REPO_ROOT / "case_studies" / "support" / "tigl_cpacs" / "tigl_support" / "__init__.py",
        REPO_ROOT / "case_studies" / "support" / "tigl_cpacs" / "tigl_support" / "core.py",
        REPO_ROOT / "case_studies" / "fixtures" / "CPACS_30_D150.xml",
    ),
}


@pytest.mark.parametrize(
    ("script_name", "expected_pass_fragment", "expected_skip_fragment"),
    [
        ("su2_cli.py", "run_su2_cfd", "SU2_CFD"),
        ("pycycle_mpcycle.py", "create_mpcycle", "pycycle.api"),
        ("tigl_cpacs.py", "open_cpacs_summary", "TiGL/TiXI"),
    ],
)
def test_case_study_scripts_run_successfully(
    script_name: str,
    expected_pass_fragment: str,
    expected_skip_fragment: str,
) -> None:
    """Each checked-in case study should emit a stable passed/skip payload."""
    for required_path in SUPPORT_REQUIREMENTS[script_name]:
        assert required_path.exists(), f"Missing checked-in support input: {required_path}"
    shutil.rmtree(
        REPO_ROOT / "artifacts" / "case_studies" / Path(script_name).stem, ignore_errors=True
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    completed = subprocess.run(
        [sys.executable, f"case_studies/{script_name}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    parsed = json.loads(completed.stdout)
    assert parsed["case_study"] == Path(script_name).stem
    assert parsed["status"] in {"passed", "skipped_unavailable"}
    rendered = json.dumps(parsed, sort_keys=True)
    if parsed["status"] == "passed":
        assert expected_pass_fragment in rendered
        assert "report" in parsed
        assert "result" in parsed
        assert "reason" not in parsed
        return
    assert expected_skip_fragment in parsed["reason"]
    assert "report" not in parsed
    assert "result" not in parsed

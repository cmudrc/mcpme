"""Serve the persisted TiGL case-study facade over stdio MCP."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from mcpme import build_manifest, serve_stdio

CASE_STUDY_ID = "tigl_cpacs"
REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPO_ROOT / "case_studies" / "support" / CASE_STUDY_ID
ARTIFACT_ROOT = REPO_ROOT / "artifacts" / "case_studies" / CASE_STUDY_ID
STATE_PATH = ARTIFACT_ROOT / "ingest_state.json"
PACKAGE_ROOT = SOURCE_ROOT / "tigl_support"


def main() -> None:
    """Load the persisted TiGL facade and serve it over stdio."""
    if not STATE_PATH.exists():
        raise FileNotFoundError(
            f"Missing persisted ingest state: {STATE_PATH}. "
            "Run case_studies/tigl_cpacs/ingest.py first."
        )

    ingest_state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    if ingest_state["status"] == "skipped_unavailable":
        raise RuntimeError(
            f"Cannot serve skipped case study {CASE_STUDY_ID}: {ingest_state['reason']}"
        )

    package_parent = str(PACKAGE_ROOT.parent.resolve())
    if package_parent not in sys.path:
        sys.path.insert(0, package_parent)

    generated_facade = Path(str(ingest_state["generated_facade"]))
    manifest = build_manifest(targets=[generated_facade], artifact_root=ARTIFACT_ROOT)
    serve_stdio(manifest)


if __name__ == "__main__":
    main()

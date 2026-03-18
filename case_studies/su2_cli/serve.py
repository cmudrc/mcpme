"""Serve the persisted SU2 case-study facade over stdio MCP."""

from __future__ import annotations

import json
from pathlib import Path

from mcpme import build_manifest, serve_stdio

CASE_STUDY_ID = "su2_cli"
REPO_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_ROOT = REPO_ROOT / "artifacts" / "case_studies" / CASE_STUDY_ID
STATE_PATH = ARTIFACT_ROOT / "ingest_state.json"


def main() -> None:
    """Load the persisted SU2 facade and serve it over stdio."""
    if not STATE_PATH.exists():
        raise FileNotFoundError(
            f"Missing persisted ingest state: {STATE_PATH}. "
            "Run case_studies/su2_cli/ingest.py first."
        )

    ingest_state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    if ingest_state["status"] == "skipped_unavailable":
        raise RuntimeError(
            f"Cannot serve skipped case study {CASE_STUDY_ID}: {ingest_state['reason']}"
        )

    generated_facade = Path(str(ingest_state["generated_facade"]))
    manifest = build_manifest(targets=[generated_facade], artifact_root=ARTIFACT_ROOT)
    serve_stdio(manifest)


if __name__ == "__main__":
    main()

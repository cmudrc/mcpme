"""Serve the generated pyCycle case-study facade over stdio MCP."""

from __future__ import annotations

from pathlib import Path

from mcpme import build_manifest, serve_stdio

CASE_STUDY_ID = "pycycle_mpcycle"
REPO_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_ROOT = REPO_ROOT / "artifacts" / "case_studies" / CASE_STUDY_ID
GENERATED_FACADE_PATH = ARTIFACT_ROOT / "generated_facade.py"


def main() -> None:
    """Load the generated pyCycle facade and serve it over stdio."""
    # The serve step only works from the persisted ingest artifact so readers
    # can inspect what was generated before it is exposed.
    if not GENERATED_FACADE_PATH.exists():
        raise FileNotFoundError(
            f"Missing generated facade artifact: {GENERATED_FACADE_PATH}. "
            "Run case_studies/pycycle_mpcycle/ingest.py first."
        )

    # Build a manifest from the saved facade and hand it to the public stdio
    # server entry point unchanged.
    manifest = build_manifest(targets=[GENERATED_FACADE_PATH], artifact_root=ARTIFACT_ROOT)
    serve_stdio(manifest)


if __name__ == "__main__":
    main()

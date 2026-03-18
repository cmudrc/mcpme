"""Serve the generated TiGL case-study facade over stdio MCP."""

from __future__ import annotations

import sys
from pathlib import Path

from mcpme import build_manifest, serve_stdio

CASE_STUDY_ID = "tigl_cpacs"
REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPO_ROOT / "case_studies" / "support" / CASE_STUDY_ID
ARTIFACT_ROOT = REPO_ROOT / "artifacts" / "case_studies" / CASE_STUDY_ID
GENERATED_FACADE_PATH = ARTIFACT_ROOT / "generated_facade.py"
PACKAGE_ROOT = SOURCE_ROOT / "tigl_support"


def main() -> None:
    """Load the generated TiGL facade and serve it over stdio."""
    if not GENERATED_FACADE_PATH.exists():
        raise FileNotFoundError(
            f"Missing generated facade artifact: {GENERATED_FACADE_PATH}. "
            "Run case_studies/tigl_cpacs/ingest.py first."
        )

    package_parent = str(PACKAGE_ROOT.parent.resolve())
    if package_parent not in sys.path:
        sys.path.insert(0, package_parent)

    manifest = build_manifest(targets=[GENERATED_FACADE_PATH], artifact_root=ARTIFACT_ROOT)
    serve_stdio(manifest)


if __name__ == "__main__":
    main()

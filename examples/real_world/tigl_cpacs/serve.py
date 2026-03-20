"""Serve the generated TiGL real-world example facade over stdio MCP."""

from __future__ import annotations

import sys
from pathlib import Path

from mcpcraft import build_manifest, serve_stdio

CASE_STUDY_ID = "tigl_cpacs"
REPO_ROOT = Path(__file__).resolve().parents[3]
SOURCE_ROOT = REPO_ROOT / "examples" / "support" / "real_world" / CASE_STUDY_ID
ARTIFACT_ROOT = REPO_ROOT / "artifacts" / "examples" / "real_world" / CASE_STUDY_ID
GENERATED_FACADE_PATH = ARTIFACT_ROOT / "generated_facade.py"
PACKAGE_ROOT = SOURCE_ROOT / "tigl_support"


def main() -> None:
    """Load the generated TiGL facade and serve it over stdio."""
    # Serving is intentionally a second phase: we only expose the previously
    # generated artifact, never regenerate it on the fly.
    if not GENERATED_FACADE_PATH.exists():
        raise FileNotFoundError(
            f"Missing generated facade artifact: {GENERATED_FACADE_PATH}. "
            "Run examples/real_world/tigl_cpacs/ingest.py first."
        )

    package_parent = str(PACKAGE_ROOT.parent.resolve())
    # The generated facade imports the tiny checked-in helper package, so make
    # that package importable before building the manifest.
    if package_parent not in sys.path:
        sys.path.insert(0, package_parent)

    # Load the saved facade through the public API and serve exactly that
    # manifest over stdio MCP.
    manifest = build_manifest(targets=[GENERATED_FACADE_PATH], artifact_root=ARTIFACT_ROOT)
    serve_stdio(manifest)


if __name__ == "__main__":
    main()

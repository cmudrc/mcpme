"""Serve the generated SU2 real-world example facade over stdio MCP."""

from __future__ import annotations

from pathlib import Path

from mcpcraft import build_manifest, serve_stdio

CASE_STUDY_ID = "su2_cli"
REPO_ROOT = Path(__file__).resolve().parents[3]
ARTIFACT_ROOT = REPO_ROOT / "artifacts" / "examples" / "real_world" / CASE_STUDY_ID
GENERATED_FACADE_PATH = ARTIFACT_ROOT / "generated_facade.py"


def main() -> None:
    """Load the generated SU2 facade and serve it over stdio."""
    # The serve phase consumes the saved artifact produced by ingest instead of
    # rescaffolding the CLI on demand.
    if not GENERATED_FACADE_PATH.exists():
        raise FileNotFoundError(
            f"Missing generated facade artifact: {GENERATED_FACADE_PATH}. "
            "Run examples/real_world/su2_cli/ingest.py first."
        )

    # Rehydrate the stored facade into a manifest and expose it over stdio MCP.
    manifest = build_manifest(targets=[GENERATED_FACADE_PATH], artifact_root=ARTIFACT_ROOT)
    serve_stdio(manifest)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Run the live raw-upstream challenge suite and emit stable reports."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from mcpme._challenges import (
    ChallengeCatalogError,
    load_challenge_catalog,
    run_challenge_suite,
    write_junit_xml,
    write_metrics_json,
    write_summary_markdown,
)


def main(argv: list[str] | None = None) -> int:
    """Run the challenge suite and write deterministic report artifacts."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalog-dir",
        type=Path,
        default=Path("challenges/catalog"),
        help="Directory containing challenge TOML files.",
    )
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=Path("artifacts/challenges/gha_subset"),
        help="Root directory for challenge artifacts and generated facades.",
    )
    parser.add_argument(
        "--metrics-json",
        type=Path,
        default=Path("artifacts/challenges/gha_subset/challenges_metrics.json"),
        help="Output path for aggregate metrics JSON.",
    )
    parser.add_argument(
        "--junit-xml",
        type=Path,
        default=Path("artifacts/challenges/gha_subset/challenges.junit.xml"),
        help="Output path for JUnit XML.",
    )
    parser.add_argument(
        "--summary-md",
        type=Path,
        default=Path("artifacts/challenges/gha_subset/summary.md"),
        help="Output path for the markdown summary.",
    )
    parser.add_argument(
        "--tier",
        choices=("gha_subset", "local_full", "all"),
        default="gha_subset",
        help="Challenge tier selector.",
    )
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[1]
    try:
        specs = load_challenge_catalog((repo_root / args.catalog_dir).resolve())
        aggregate = run_challenge_suite(
            specs,
            repo_root=repo_root,
            artifact_root=(repo_root / args.artifact_root).resolve(),
            selected_tier=args.tier,
        )
        write_metrics_json(aggregate, (repo_root / args.metrics_json).resolve())
        write_junit_xml(aggregate, (repo_root / args.junit_xml).resolve())
        write_summary_markdown(aggregate, (repo_root / args.summary_md).resolve())
    except ChallengeCatalogError as error:
        print(f"Challenge catalog error: {error}", file=sys.stderr)
        return 1
    except Exception as error:
        print(f"Challenge harness error: {error}", file=sys.stderr)
        return 1
    print(
        "Challenge suite completed: "
        f"{aggregate.passed}/{aggregate.total} passed, "
        f"{aggregate.failed} failed, "
        f"{aggregate.skipped_unavailable} skipped."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

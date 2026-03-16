#!/usr/bin/env python3
"""Generate the reduced live challenge subset SVG badge from metrics JSON."""

from __future__ import annotations

import json
from pathlib import Path

from mcpme._challenges import ChallengeAggregate, ChallengeResult, render_badge_svg

DEFAULT_METRICS_JSON = Path("artifacts/challenges/gha_subset/challenges_metrics.json")
DEFAULT_BADGE_SVG = Path(".github/badges/challenges-live-subset.svg")


def main() -> None:
    """Read challenge metrics and write the SVG badge."""
    data = json.loads(DEFAULT_METRICS_JSON.read_text(encoding="utf-8"))
    results = tuple(
        ChallengeResult(
            id=result["id"],
            title=result["title"],
            tier=result["tier"],
            style=result["style"],
            slice=result["slice"],
            status=result["status"],
            message=result["message"],
            generated_tools=tuple(result.get("generatedTools", [])),
            steps=(),
            scaffold_path=result.get("scaffoldPath"),
            notes=result.get("notes"),
        )
        for result in data.get("results", [])
    )
    aggregate = ChallengeAggregate(
        suite_name=str(data.get("suite", "live_raw_upstream")),
        selected_tier=str(data.get("selectedTier", "gha_subset")),
        results=results,
    )
    badge = render_badge_svg(aggregate)
    DEFAULT_BADGE_SVG.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_BADGE_SVG.write_text(badge, encoding="utf-8")
    print(f"Wrote {DEFAULT_BADGE_SVG}")


if __name__ == "__main__":
    main()

"""Deterministic stand-in solver used by the subprocess example."""

from __future__ import annotations

import json
from pathlib import Path


def main() -> None:
    """Read the rendered deck and write deterministic outputs."""
    deck = json.loads(Path("deck.json").read_text(encoding="utf-8"))
    lift = round(deck["velocity"] * deck["area"] * 0.5, 3)
    Path("result.json").write_text(
        json.dumps({"case_name": deck["case_name"], "lift": lift}, sort_keys=True),
        encoding="utf-8",
    )
    reports = Path("reports")
    reports.mkdir(exist_ok=True)
    (reports / "summary.txt").write_text(
        f"case={deck['case_name']} lift={lift}\n",
        encoding="utf-8",
    )
    print("solver finished")


if __name__ == "__main__":
    main()

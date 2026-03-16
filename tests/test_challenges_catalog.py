"""Tests for live challenge catalog parsing and validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from mcpme._challenges import ChallengeCatalogError, load_challenge_catalog


def test_load_challenge_catalog_rejects_duplicate_ids(tmp_path: Path) -> None:
    """Duplicate challenge ids should fail fast with a clear catalog error."""
    catalog_dir = tmp_path / "catalog"
    catalog_dir.mkdir()
    for name in ("alpha", "beta"):
        (catalog_dir / f"{name}.toml").write_text(
            "\n".join(
                [
                    'id = "duplicate"',
                    'title = "Duplicate"',
                    'tier = "gha_subset"',
                    'style = "package"',
                    'slice = "systems"',
                    "",
                    "[target]",
                    'kind = "package"',
                    'value = "demo_pkg"',
                    "",
                    "[scaffold]",
                    'kind = "package"',
                    "",
                    "[smoke]",
                    "[[smoke.steps]]",
                    'tool = "demo"',
                    "",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

    with pytest.raises(ChallengeCatalogError, match="Duplicate challenge id"):
        load_challenge_catalog(catalog_dir)


def test_load_challenge_catalog_rejects_invalid_metadata(tmp_path: Path) -> None:
    """Invalid tiers and scaffold-target mismatches should be explicit."""
    catalog_dir = tmp_path / "catalog"
    catalog_dir.mkdir()
    (catalog_dir / "bad.toml").write_text(
        "\n".join(
            [
                'id = "bad"',
                'title = "Bad"',
                'tier = "not_real"',
                'style = "package"',
                'slice = "systems"',
                "",
                "[target]",
                'kind = "package"',
                'value = "demo_pkg"',
                "",
                "[scaffold]",
                'kind = "command"',
                "",
                "[smoke]",
                "[[smoke.steps]]",
                'tool = "demo"',
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ChallengeCatalogError, match="tier must be one of"):
        load_challenge_catalog(catalog_dir)

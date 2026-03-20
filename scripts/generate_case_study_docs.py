#!/usr/bin/env python3
"""Compatibility wrapper for the unified example docs generator."""

from __future__ import annotations

import runpy
from pathlib import Path


def main() -> int:
    """Delegate to ``generate_example_docs.py``."""
    script_path = Path(__file__).with_name("generate_example_docs.py")
    namespace = runpy.run_path(str(script_path))
    return int(namespace["main"]())


if __name__ == "__main__":
    raise SystemExit(main())

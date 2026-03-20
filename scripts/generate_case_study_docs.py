#!/usr/bin/env python3
"""Compatibility wrapper for the unified example docs generator."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def main() -> int:
    """Delegate to ``generate_example_docs.py``."""
    script_path = Path(__file__).with_name("generate_example_docs.py")
    spec = importlib.util.spec_from_file_location("_generate_example_docs", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load example docs generator from {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return int(module.main())


if __name__ == "__main__":
    raise SystemExit(main())

"""Tests for the optional live challenge dependency installer."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_module(path: Path) -> object:
    """Load one script module from disk for direct helper testing."""
    spec = importlib.util.spec_from_file_location("install_challenge_deps", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_install_challenge_deps_helper_plans_cover_supported_profiles() -> None:
    """The installer helpers should expose stable profile and asset selections."""
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "install_challenge_deps.py"
    module = _load_module(script_path)

    assert module._python_extra_for_profile("subset") == "challenge-subset"
    assert module._python_extra_for_profile("full") == "challenge-full"
    assert module._external_tools_for_profile("subset") == ("gmsh",)
    assert module._external_tools_for_profile("full") == ("gmsh", "avl", "xfoil", "su2")
    assert module._su2_asset_url("Darwin").endswith("SU2-v8.4.0-macos64.zip")
    assert module._su2_asset_url("Linux").endswith("SU2-v8.4.0-linux64.zip")
    assert module._avl_binary_url("Darwin", "arm64").endswith("avl3.40_execs/DARWINM1/avl")
    assert module._avl_binary_url("Darwin", "x86_64").endswith("avl3.40_execs/DARWIN64/avl")


def test_install_challenge_deps_env_script_uses_repo_local_tool_prefix() -> None:
    """The generated env helper should expose the repo-local tool shims."""
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "install_challenge_deps.py"
    module = _load_module(script_path)

    repo_root = Path("/tmp/mcpwrap")
    install_root = repo_root / ".challenge-tools"
    su2_home = install_root / "su2" / module.SU2_VERSION

    rendered = module._render_env_script(repo_root, install_root, su2_home)

    assert (
        'export PATH="/tmp/mcpwrap/.challenge-tools/bin:/tmp/mcpwrap/.venv/bin:$PATH"' in rendered
    )
    assert 'export SU2_HOME="/tmp/mcpwrap/.challenge-tools/su2/8.4.0"' in rendered
    assert 'export SU2_RUN="$SU2_HOME/bin"' in rendered

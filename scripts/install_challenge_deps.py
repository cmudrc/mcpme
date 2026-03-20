#!/usr/bin/env python3
"""Install optional live challenge dependencies into a repo-local prefix."""

from __future__ import annotations

import argparse
import json
import platform
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path

XFOIL_VERSION = "6.996"
SU2_VERSION = "8.4.0"
AVL_VERSION = "3.40b"

PROFILE_TO_EXTRA = {
    "subset": "challenge-subset",
    "full": "challenge-full",
}

PROFILE_TO_EXTERNAL_TOOLS = {
    "subset": ("gmsh",),
    "full": ("gmsh", "avl", "xfoil", "su2"),
}


@dataclass(frozen=True)
class InstalledTool:
    """Describe one installed optional challenge dependency."""

    name: str
    version: str
    source_url: str
    installed_path: str
    notes: str | None = None


def _repo_root() -> Path:
    """Return the repository root."""
    return Path(__file__).resolve().parents[1]


def _default_install_root(repo_root: Path) -> Path:
    """Return the default repo-local challenge tool prefix."""
    return repo_root / ".challenge-tools"


def _python_extra_for_profile(profile: str) -> str:
    """Return the Python optional-dependency extra name for one profile."""
    return PROFILE_TO_EXTRA[profile]


def _external_tools_for_profile(profile: str) -> tuple[str, ...]:
    """Return the external CLI tools required for one profile."""
    return PROFILE_TO_EXTERNAL_TOOLS[profile]


def _print_status(message: str) -> None:
    """Emit one stable installer progress line."""
    print(f"[challenge-deps] {message}")


def _run(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run one command with a stable echoed shell line."""
    _print_status(f"+ {shlex.join(command)}")
    return subprocess.run(
        command,
        check=True,
        cwd=cwd,
        env=env,
        input=input_text,
        text=True,
        capture_output=capture_output,
    )


def _download(url: str, destination: Path) -> None:
    """Download one URL to disk."""
    _print_status(f"Downloading {url}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url) as response, destination.open("wb") as handle:
        shutil.copyfileobj(response, handle)


def _write_executable(path: Path, text: str) -> None:
    """Write one executable text file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


def _venv_python(repo_root: Path) -> Path:
    """Return the preferred Python executable for dependency installation."""
    candidate = repo_root / ".venv" / "bin" / "python"
    if candidate.exists():
        return candidate
    return Path(sys.executable)


def _pkg_config_flag(flag: str, package: str) -> str:
    """Return one pkg-config flag payload."""
    result = subprocess.run(
        ["pkg-config", flag, package],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _ensure_homebrew_formulae(formulae: list[str]) -> None:
    """Install any requested Homebrew formulae."""
    if not formulae:
        return
    unique = list(dict.fromkeys(formulae))
    _run(["brew", "install", *unique])


def _safe_extract_tar_gz(archive_path: Path, destination: Path) -> None:
    """Extract one trusted tar.gz archive."""
    with tarfile.open(archive_path, "r:gz") as archive:
        archive.extractall(destination, filter="data")


def _find_unique_path(root: Path, name: str) -> Path:
    """Locate one path by basename within a tree."""
    matches = sorted(path for path in root.rglob(name) if path.name == name)
    if not matches:
        raise FileNotFoundError(f"Could not find {name!r} under {root}.")
    return matches[0]


def _smoke_check_gmsh(binary_path: Path) -> None:
    """Verify that gmsh responds."""
    _run([str(binary_path), "-help"], capture_output=True)


def _smoke_check_avl(binary_path: Path) -> None:
    """Verify that AVL starts and exits cleanly in batch mode."""
    _run([str(binary_path)], input_text="quit\n", capture_output=True)


def _smoke_check_xfoil(binary_path: Path) -> None:
    """Verify that XFOIL starts and exits cleanly in batch mode."""
    _run([str(binary_path)], input_text="quit\n", capture_output=True)


def _smoke_check_su2(binary_path: Path) -> None:
    """Verify that SU2 prints its help text."""
    result = _run([str(binary_path), "-h"], capture_output=True)
    if "SU2" not in result.stdout:
        raise RuntimeError(f"Unexpected SU2 help output from {binary_path}.")


def _ensure_python_extra(repo_root: Path, profile: str) -> None:
    """Install the matching Python challenge extra into the active environment."""
    python = _venv_python(repo_root)
    extra = _python_extra_for_profile(profile)
    _run([str(python), "-m", "pip", "install", "-e", f".[{extra}]"], cwd=repo_root)


def _ensure_gmsh(install_root: Path, force: bool) -> InstalledTool:
    """Ensure that gmsh is reachable through the repo-local tool prefix."""
    link_path = install_root / "bin" / "gmsh"
    if link_path.exists() and not force:
        _smoke_check_gmsh(link_path)
        return InstalledTool(
            name="gmsh",
            version="system",
            source_url="https://gmsh.info/",
            installed_path=str(link_path),
        )

    gmsh_path_text = shutil.which("gmsh")
    if gmsh_path_text is None:
        if platform.system() == "Darwin" and shutil.which("brew"):
            _ensure_homebrew_formulae(["gmsh"])
            gmsh_path_text = shutil.which("gmsh")
        if gmsh_path_text is None:
            raise RuntimeError(
                "gmsh is not installed. On macOS, install Homebrew and rerun this script."
            )
    gmsh_path = Path(gmsh_path_text).resolve()
    link_path.parent.mkdir(parents=True, exist_ok=True)
    if link_path.exists() or link_path.is_symlink():
        link_path.unlink()
    link_path.symlink_to(gmsh_path)
    _smoke_check_gmsh(link_path)
    return InstalledTool(
        name="gmsh",
        version="system",
        source_url="https://gmsh.info/",
        installed_path=str(link_path),
        notes=f"Symlinked to {gmsh_path}.",
    )


def _avl_binary_url(system: str, machine: str) -> str:
    """Return the official AVL binary URL for one host."""
    if system == "Darwin" and machine in {"arm64", "aarch64"}:
        return "https://web.mit.edu/drela/Public/web/avl/avl3.40_execs/DARWINM1/avl"
    if system == "Darwin" and machine == "x86_64":
        return "https://web.mit.edu/drela/Public/web/avl/avl3.40_execs/DARWIN64/avl"
    if system == "Linux" and machine == "x86_64":
        return "https://web.mit.edu/drela/Public/web/avl/avl3.40_execs/LINUX64/avl"
    raise RuntimeError(f"AVL binary install is not supported on {system} {machine}.")


def _ensure_avl(install_root: Path, force: bool) -> InstalledTool:
    """Install the official AVL binary into the repo-local tool prefix."""
    binary_path = install_root / "bin" / "avl"
    if binary_path.exists() and not force:
        _smoke_check_avl(binary_path)
        return InstalledTool(
            name="avl",
            version=AVL_VERSION,
            source_url=_avl_binary_url(platform.system(), platform.machine()),
            installed_path=str(binary_path),
        )

    url = _avl_binary_url(platform.system(), platform.machine())
    with tempfile.TemporaryDirectory(prefix="mcpwrap-avl-") as temp_dir:
        temp_path = Path(temp_dir)
        download_path = temp_path / "avl"
        _download(url, download_path)
        binary_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(download_path, binary_path)
        binary_path.chmod(0o755)
    _smoke_check_avl(binary_path)
    return InstalledTool(
        name="avl",
        version=AVL_VERSION,
        source_url=url,
        installed_path=str(binary_path),
        notes="Official AVL binary installed into the repo-local challenge tool prefix.",
    )


def _x11_flags_for_xfoil() -> tuple[str, str]:
    """Return X11 include and link flags suitable for XFOIL builds."""
    missing_formulae: list[str] = []
    if shutil.which("gfortran") is None and platform.system() == "Darwin" and shutil.which("brew"):
        missing_formulae.append("gcc")
    if (
        shutil.which("pkg-config") is None
        and platform.system() == "Darwin"
        and shutil.which("brew")
    ):
        missing_formulae.append("pkgconf")
    if missing_formulae:
        _ensure_homebrew_formulae(missing_formulae)

    try:
        cflags = _pkg_config_flag("--cflags", "x11")
        libs = _pkg_config_flag("--libs", "x11")
    except (OSError, subprocess.CalledProcessError):
        if platform.system() == "Darwin" and shutil.which("brew"):
            _ensure_homebrew_formulae(["libx11", "libxext", "xorgproto", "pkgconf", "gcc"])
            cflags = _pkg_config_flag("--cflags", "x11")
            libs = _pkg_config_flag("--libs", "x11")
        else:
            raise RuntimeError(
                "Could not resolve X11 build flags for XFOIL. Install pkg-config plus X11 "
                "development headers and rerun this script."
            ) from None

    if shutil.which("gfortran") is None:
        raise RuntimeError("XFOIL builds require gfortran to be installed.")
    return cflags, libs


def _ensure_xfoil(install_root: Path, force: bool) -> InstalledTool:
    """Build and install XFOIL from the official source archive."""
    binary_path = install_root / "bin" / "xfoil"
    if binary_path.exists() and not force:
        _smoke_check_xfoil(binary_path)
        return InstalledTool(
            name="xfoil",
            version=XFOIL_VERSION,
            source_url=f"https://web.mit.edu/drela/Public/web/xfoil/xfoil{XFOIL_VERSION}.tgz",
            installed_path=str(binary_path),
        )

    cflags, libs = _x11_flags_for_xfoil()
    legacy_flags = "-O -fdefault-real-8 -fallow-argument-mismatch -std=legacy"
    with tempfile.TemporaryDirectory(prefix="mcpwrap-xfoil-") as temp_dir:
        temp_path = Path(temp_dir)
        archive_path = temp_path / f"xfoil{XFOIL_VERSION}.tgz"
        _download(
            f"https://web.mit.edu/drela/Public/web/xfoil/xfoil{XFOIL_VERSION}.tgz",
            archive_path,
        )
        _safe_extract_tar_gz(archive_path, temp_path)
        source_root = _find_unique_path(temp_path, "README").parent
        install_bin = install_root / "bin"
        install_bin.mkdir(parents=True, exist_ok=True)
        _run(
            [
                "make",
                "-C",
                str(source_root / "plotlib"),
                "gfortranDP",
                f"INCDIR={cflags}",
                f"LINKLIB={libs}",
            ]
        )
        _run(
            [
                "make",
                "-C",
                str(source_root / "bin"),
                "-f",
                "Makefile_gfortran",
                "xfoil",
                f"PLTLIB={libs}",
                f"BINDIR={install_bin}",
                "INSTALLCMD=cp",
                f"FFLAGS={legacy_flags}",
                f"FFLOPT={legacy_flags}",
            ]
        )
    _smoke_check_xfoil(binary_path)
    return InstalledTool(
        name="xfoil",
        version=XFOIL_VERSION,
        source_url=f"https://web.mit.edu/drela/Public/web/xfoil/xfoil{XFOIL_VERSION}.tgz",
        installed_path=str(binary_path),
        notes="Built from source with gfortran legacy-compatibility flags for modern GCC.",
    )


def _su2_asset_url(system: str) -> str:
    """Return the official SU2 binary-archive URL for one host OS."""
    if system == "Darwin":
        return f"https://github.com/su2code/SU2/releases/download/v{SU2_VERSION}/SU2-v{SU2_VERSION}-macos64.zip"
    if system == "Linux":
        return f"https://github.com/su2code/SU2/releases/download/v{SU2_VERSION}/SU2-v{SU2_VERSION}-linux64.zip"
    raise RuntimeError(f"SU2 binary install is not supported on {system}.")


def _copytree_replace(source: Path, destination: Path) -> None:
    """Replace one tree with another."""
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)


def _create_su2_wrappers(install_root: Path, su2_home: Path) -> list[Path]:
    """Create repo-local wrappers for the SU2 executables."""
    wrappers: list[Path] = []
    bin_dir = su2_home / "bin"
    for binary in sorted(bin_dir.iterdir()):
        if not binary.is_file() or binary.suffix:
            continue
        if not binary.name.startswith("SU2_"):
            continue
        binary.chmod(0o755)
        wrapper_path = install_root / "bin" / binary.name
        wrapper_text = "\n".join(
            [
                "#!/bin/sh",
                "set -eu",
                f'SU2_HOME="{su2_home}"',
                'SU2_RUN="$SU2_HOME/bin"',
                "export SU2_HOME",
                "export SU2_RUN",
                'export PATH="$SU2_RUN:$PATH"',
                'if [ -n "${PYTHONPATH:-}" ]; then',
                '  export PYTHONPATH="$SU2_RUN:$PYTHONPATH"',
                "else",
                '  export PYTHONPATH="$SU2_RUN"',
                "fi",
                f'exec "$SU2_RUN/{binary.name}" "$@"',
                "",
            ]
        )
        _write_executable(wrapper_path, wrapper_text)
        wrappers.append(wrapper_path)
    return wrappers


def _ensure_su2(install_root: Path, force: bool) -> InstalledTool:
    """Install the official SU2 binary distribution into the repo-local tool prefix."""
    wrapper_path = install_root / "bin" / "SU2_CFD"
    su2_home = install_root / "su2" / SU2_VERSION
    if wrapper_path.exists() and not force:
        _smoke_check_su2(wrapper_path)
        return InstalledTool(
            name="su2",
            version=SU2_VERSION,
            source_url=_su2_asset_url(platform.system()),
            installed_path=str(wrapper_path),
            notes=f"Official SU2 payload lives under {su2_home}.",
        )

    url = _su2_asset_url(platform.system())
    with tempfile.TemporaryDirectory(prefix="mcpwrap-su2-") as temp_dir:
        temp_path = Path(temp_dir)
        archive_path = temp_path / "su2.zip"
        outer_dir = temp_path / "outer"
        payload_dir = temp_path / "payload"
        _download(url, archive_path)
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(outer_dir)
        search_root = outer_dir
        if not list(outer_dir.rglob("SU2_CFD")):
            nested_archives = sorted(path for path in outer_dir.rglob("*.zip") if path.is_file())
            if len(nested_archives) != 1:
                raise RuntimeError("Could not locate the nested SU2 payload archive.")
            with zipfile.ZipFile(nested_archives[0]) as nested_archive:
                nested_archive.extractall(payload_dir)
            search_root = payload_dir
        binary_path = _find_unique_path(search_root, "SU2_CFD")
        payload_root = binary_path.parent.parent
        su2_home.parent.mkdir(parents=True, exist_ok=True)
        _copytree_replace(payload_root, su2_home)

    (install_root / "bin").mkdir(parents=True, exist_ok=True)
    _create_su2_wrappers(install_root, su2_home)
    _smoke_check_su2(wrapper_path)
    return InstalledTool(
        name="su2",
        version=SU2_VERSION,
        source_url=url,
        installed_path=str(wrapper_path),
        notes=f"Official SU2 payload lives under {su2_home}.",
    )


def _render_env_script(repo_root: Path, install_root: Path, su2_home: Path | None) -> str:
    """Render one shell snippet that exposes repo-local challenge tools."""
    lines = [
        "#!/bin/sh",
        "set -eu",
        f'export PATH="{install_root / "bin"}:{repo_root / ".venv" / "bin"}:$PATH"',
    ]
    if su2_home is not None:
        lines.extend(
            [
                f'export SU2_HOME="{su2_home}"',
                'export SU2_RUN="$SU2_HOME/bin"',
                'if [ -n "${PYTHONPATH:-}" ]; then',
                '  export PYTHONPATH="$SU2_RUN:$PYTHONPATH"',
                "else",
                '  export PYTHONPATH="$SU2_RUN"',
                "fi",
            ]
        )
    lines.append("")
    return "\n".join(lines)


def _write_manifest(
    install_root: Path, profile: str, tools: list[InstalledTool], env_script_path: Path
) -> None:
    """Persist one deterministic installer manifest."""
    payload = {
        "profile": profile,
        "tools": [asdict(tool) for tool in tools],
        "env_script": str(env_script_path),
    }
    manifest_path = install_root / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    """Install optional live challenge dependencies."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile",
        choices=tuple(PROFILE_TO_EXTRA),
        default="full",
        help="Challenge runtime profile to install. Defaults to the full local lane.",
    )
    parser.add_argument(
        "--install-root",
        type=Path,
        default=None,
        help="Optional repo-local install prefix. Defaults to .challenge-tools.",
    )
    parser.add_argument(
        "--skip-python",
        action="store_true",
        help="Skip pip installation of the matching Python challenge extra.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Reinstall tools even when repo-local copies already exist.",
    )
    args = parser.parse_args()

    repo_root = _repo_root()
    install_root = (args.install_root or _default_install_root(repo_root)).resolve()
    install_root.mkdir(parents=True, exist_ok=True)

    installed_tools: list[InstalledTool] = []
    if not args.skip_python:
        _ensure_python_extra(repo_root, args.profile)

    for tool_name in _external_tools_for_profile(args.profile):
        if tool_name == "gmsh":
            installed_tools.append(_ensure_gmsh(install_root, args.force))
        elif tool_name == "avl":
            installed_tools.append(_ensure_avl(install_root, args.force))
        elif tool_name == "xfoil":
            installed_tools.append(_ensure_xfoil(install_root, args.force))
        elif tool_name == "su2":
            installed_tools.append(_ensure_su2(install_root, args.force))
        else:
            raise AssertionError(f"Unhandled tool install target: {tool_name}")

    su2_home = install_root / "su2" / SU2_VERSION
    env_script_path = install_root / "env.sh"
    _write_executable(
        env_script_path,
        _render_env_script(repo_root, install_root, su2_home if su2_home.exists() else None),
    )
    _write_manifest(install_root, args.profile, installed_tools, env_script_path)

    _print_status(f"Installed profile {args.profile!r} into {install_root}")
    _print_status(f"Source this shell helper before ad hoc runs: . {env_script_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

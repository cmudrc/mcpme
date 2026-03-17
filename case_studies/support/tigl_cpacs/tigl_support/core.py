"""JSON-friendly TiGL/TiXI helper functions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tigl3 import tigl3wrapper
from tixi3 import tixi3wrapper


def _close_handles(tixi_handle: object, tigl_handle: object) -> None:
    """Close TiGL and TiXI handles when the runtime exposes cleanup methods."""
    close_tigl = getattr(tigl_handle, "close", None)
    if callable(close_tigl):
        close_tigl()
    close_tixi = getattr(tixi_handle, "close", None)
    if callable(close_tixi):
        close_tixi()
    cleanup_tixi = getattr(tixi_handle, "cleanup", None)
    if callable(cleanup_tixi):
        cleanup_tixi()


def open_cpacs_summary(cpacs_path: Path) -> dict[str, Any]:
    """Open a CPACS file through TiXI and TiGL and return a stable summary.

    :param cpacs_path: Path to a CPACS XML file.
    :returns: JSON-friendly TiGL configuration summary.
    """
    tixi_handle = tixi3wrapper.Tixi3()
    tigl_handle = tigl3wrapper.Tigl3()
    tixi_handle.open(str(cpacs_path))
    tigl_handle.open(tixi_handle, "")
    try:
        wing_count = int(tigl_handle.getWingCount())
        fuselage_count = int(tigl_handle.getFuselageCount())
        first_wing_uid = tigl_handle.wingGetUID(1) if wing_count else None
        return {
            "cpacs_path": str(cpacs_path),
            "first_wing_uid": first_wing_uid,
            "fuselage_count": fuselage_count,
            "tigl_version": getattr(tigl_handle, "version", "unknown"),
            "wing_count": wing_count,
        }
    finally:
        _close_handles(tixi_handle, tigl_handle)

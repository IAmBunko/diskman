"""Host OS detection for DiskMan backends."""

from __future__ import annotations

import sys
from typing import Literal

PlatformName = Literal["linux", "darwin", "windows", "unknown"]


def get_platform() -> PlatformName:
    """Return a coarse platform id used to select backends."""
    p = sys.platform
    if p.startswith("linux"):
        return "linux"
    if p == "darwin":
        return "darwin"
    if p in ("win32", "cygwin", "msys"):
        return "windows"
    return "unknown"


def platform_label() -> str:
    """Human-readable platform name for UI/status."""
    return {
        "linux": "Linux",
        "darwin": "macOS",
        "windows": "Windows",
        "unknown": sys.platform or "unknown",
    }.get(get_platform(), sys.platform)

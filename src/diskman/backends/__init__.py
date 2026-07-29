"""OS-specific device inventory and action backends."""

from __future__ import annotations

from diskman.backends.base import Backend
from diskman.platform import get_platform


def get_backend() -> Backend:
    """Return the backend for the current host OS."""
    plat = get_platform()
    if plat == "linux":
        from diskman.backends.linux import LinuxBackend

        return LinuxBackend()
    if plat == "darwin":
        from diskman.backends.darwin import DarwinBackend

        return DarwinBackend()
    from diskman.backends.unsupported import UnsupportedBackend

    return UnsupportedBackend(plat)

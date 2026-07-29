"""Fallback backend for platforms without an implementation yet."""

from __future__ import annotations

from typing import Optional

from diskman.backends.common import ActionResult
from diskman.models import BlockDevice
from diskman.platform import platform_label


class UnsupportedBackend:
    name = "unsupported"

    def __init__(self, plat: str) -> None:
        self._plat = plat

    def _error(self) -> ActionResult:
        return ActionResult(
            False,
            f"DiskMan does not support {platform_label()} ({self._plat}) yet. "
            "Supported: Linux, macOS.",
        )

    def list_devices(self) -> list[BlockDevice]:
        raise RuntimeError(
            f"DiskMan does not support {platform_label()} ({self._plat}) yet. "
            "Supported: Linux, macOS."
        )

    def available_filesystems(self) -> list[str]:
        return []

    def mount(self, dev: BlockDevice) -> ActionResult:
        return self._error()

    def unmount(self, dev: BlockDevice) -> ActionResult:
        return self._error()

    def format(
        self,
        dev: BlockDevice,
        fstype: str,
        label: Optional[str],
        *,
        confirm_name: str,
    ) -> ActionResult:
        return self._error()

    def privilege_hint(self) -> str:
        return "unsupported platform"

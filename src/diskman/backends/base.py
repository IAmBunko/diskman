"""Backend protocol for inventory and device actions."""

from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

from diskman.models import BlockDevice


@runtime_checkable
class ActionResultLike(Protocol):
    ok: bool
    message: str
    stdout: str
    stderr: str
    returncode: int


@runtime_checkable
class Backend(Protocol):
    """Platform implementation of discovery + mount/unmount/format."""

    name: str

    def list_devices(self) -> list[BlockDevice]:
        """Return top-level block devices (disks with children)."""
        ...

    def available_filesystems(self) -> list[str]:
        """Filesystem types that can be selected for format on this OS."""
        ...

    def mount(self, dev: BlockDevice) -> ActionResultLike:
        ...

    def unmount(self, dev: BlockDevice) -> ActionResultLike:
        ...

    def format(
        self,
        dev: BlockDevice,
        fstype: str,
        label: Optional[str],
        *,
        confirm_name: str,
    ) -> ActionResultLike:
        ...

    def privilege_hint(self) -> str:
        """Short status string for how elevation works on this platform."""
        ...

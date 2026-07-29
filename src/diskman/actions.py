"""Mount, unmount, and format via the platform backend."""

from __future__ import annotations

from typing import Optional

from diskman.backends import get_backend
from diskman.backends.common import ActionResult
from diskman.models import BlockDevice
from diskman.safety import SafetyResult, can_format

# Re-export for UI / callers
__all__ = [
    "ActionResult",
    "available_filesystems",
    "mount_device",
    "unmount_device",
    "format_device",
    "describe_format_check",
    "privilege_hint",
]


def available_filesystems() -> list[str]:
    """Return FS types the current backend can format."""
    return get_backend().available_filesystems()


def privilege_hint() -> str:
    return get_backend().privilege_hint()


def mount_device(dev: BlockDevice) -> ActionResult:
    result = get_backend().mount(dev)
    return ActionResult(
        result.ok,
        result.message,
        stdout=getattr(result, "stdout", "") or "",
        stderr=getattr(result, "stderr", "") or "",
        returncode=getattr(result, "returncode", 0) or 0,
    )


def unmount_device(dev: BlockDevice) -> ActionResult:
    result = get_backend().unmount(dev)
    return ActionResult(
        result.ok,
        result.message,
        stdout=getattr(result, "stdout", "") or "",
        stderr=getattr(result, "stderr", "") or "",
        returncode=getattr(result, "returncode", 0) or 0,
    )


def format_device(
    dev: BlockDevice,
    fstype: str,
    label: Optional[str] = None,
    *,
    confirm_name: str,
) -> ActionResult:
    """Wipe / erase and create a new filesystem. Requires exact name confirm."""
    try:
        result = get_backend().format(dev, fstype, label, confirm_name=confirm_name)
        return ActionResult(
            result.ok,
            result.message,
            stdout=getattr(result, "stdout", "") or "",
            stderr=getattr(result, "stderr", "") or "",
            returncode=getattr(result, "returncode", 0) or 0,
        )
    except Exception as exc:  # noqa: BLE001 — surface any unexpected error to UI
        return ActionResult(False, f"Format error: {exc}")


def describe_format_check(dev: BlockDevice) -> SafetyResult:
    return can_format(dev)

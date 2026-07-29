"""Discover block devices via the platform backend."""

from __future__ import annotations

from typing import Optional

from diskman.backends import get_backend
from diskman.models import BlockDevice, human_size


def list_devices() -> list[BlockDevice]:
    """Return top-level block devices for the current OS."""
    return get_backend().list_devices()


def find_device(devices: list[BlockDevice], name_or_path: str) -> Optional[BlockDevice]:
    """Find a device by name (sda1, disk2s1) or path (/dev/sda1, /dev/disk2s1)."""
    target = name_or_path.strip()
    if target.startswith("/dev/"):
        target_name = target[len("/dev/") :]
        target_path = target
    else:
        target_name = target
        target_path = f"/dev/{target}"

    for root in devices:
        for dev in root.walk():
            if dev.name == target_name or dev.path == target_path:
                return dev
    return None


def format_inventory(devices: list[BlockDevice]) -> str:
    """Plain-text inventory for --list mode."""
    lines: list[str] = []
    for root in devices:
        for dev in root.walk():
            depth = 0
            if dev.pkname:
                depth = 1
            # Nested APFS volumes under partitions
            if dev.pkname and any(
                c.name == dev.pkname for r in devices for c in r.walk() if c.pkname
            ):
                # Approximate deeper indent when parent is also a child
                depth = 1
                parent_is_child = any(
                    c.name == dev.pkname and c.pkname for r in devices for c in r.walk()
                )
                if parent_is_child:
                    depth = 2
            indent = "  " * depth
            bits = [
                f"{indent}{dev.name}",
                human_size(dev.size),
                dev.dev_type,
            ]
            if dev.fstype:
                bits.append(dev.fstype)
            if dev.label:
                bits.append(f'"{dev.label}"')
            if dev.mountpoint:
                bits.append(f"@ {dev.mountpoint}")
            if dev.model and dev.is_disk:
                bits.append(dev.model.strip())
            if dev.transport and dev.is_disk:
                bits.append(f"[{dev.transport}]")
            lines.append("  ".join(bits))
    return "\n".join(lines)

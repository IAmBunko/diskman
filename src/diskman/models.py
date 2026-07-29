"""Block device data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


def human_size(num_bytes: Optional[int]) -> str:
    """Format a byte count as a human-readable size string."""
    if num_bytes is None:
        return "—"
    try:
        n = float(num_bytes)
    except (TypeError, ValueError):
        return "—"
    units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"]
    for unit in units:
        if abs(n) < 1024.0 or unit == units[-1]:
            if unit == "B":
                return f"{int(n)} {unit}"
            return f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} PiB"


@dataclass
class BlockDevice:
    """A block device (disk, partition, volume, or other)."""

    name: str
    path: str
    size: Optional[int] = None
    dev_type: str = "disk"  # disk | part | loop | rom | container | ...
    fstype: Optional[str] = None
    mountpoint: Optional[str] = None
    label: Optional[str] = None
    uuid: Optional[str] = None
    model: Optional[str] = None
    serial: Optional[str] = None
    transport: Optional[str] = None
    rotational: Optional[bool] = None
    removable: Optional[bool] = None
    hotplug: Optional[bool] = None
    vendor: Optional[str] = None
    state: Optional[str] = None
    pkname: Optional[str] = None
    parttype: Optional[str] = None
    parttypename: Optional[str] = None
    partuuid: Optional[str] = None
    pttype: Optional[str] = None
    fsavail: Optional[int] = None
    fsuse_pct: Optional[str] = None
    fssize: Optional[int] = None
    # All mount targets for this device (btrfs subvolumes, bind mounts, etc.)
    mountpoints: list[str] = field(default_factory=list)
    children: list[BlockDevice] = field(default_factory=list)

    @property
    def is_disk(self) -> bool:
        return self.dev_type in ("disk", "container")

    @property
    def is_partition(self) -> bool:
        return self.dev_type == "part"

    @property
    def is_mounted(self) -> bool:
        if self.mountpoints:
            return any(mp and mp != "[SWAP]" for mp in self.mountpoints)
        mp = self.mountpoint
        return bool(mp) and mp not in ("", "[SWAP]")

    @property
    def is_swap(self) -> bool:
        if (self.fstype or "").lower() == "swap":
            return True
        if self.mountpoint == "[SWAP]":
            return True
        return "[SWAP]" in self.mountpoints

    @property
    def is_virtual(self) -> bool:
        name = (self.name or "").lower()
        if (
            name.startswith("zram")
            or name.startswith("loop")
            or name.startswith("ram")
            or name.startswith("dm-")
            or self.dev_type in ("loop", "rom")
        ):
            return True
        # Linux nbd / md pseudo devices
        if name.startswith("nbd") or name.startswith("md"):
            return True
        return False

    @property
    def size_human(self) -> str:
        return human_size(self.size)

    def tree_label(self) -> str:
        """Short label for the device tree."""
        parts = [self.name, self.size_human]
        if self.is_disk:
            if self.transport:
                parts.append(self.transport)
            elif self.model:
                parts.append(self.model.strip()[:24])
        else:
            if self.fstype:
                parts.append(self.fstype)
            if self.label:
                parts.append(self.label)
            mps = [m for m in self.effective_mountpoints() if m and m != "[SWAP]"]
            if mps:
                if "/" in mps:
                    parts.append("/")
                elif self.mountpoint:
                    parts.append(self.mountpoint)
                else:
                    parts.append(mps[0])
            elif self.mountpoint:
                parts.append(self.mountpoint)
        return "  ".join(parts)

    def effective_mountpoints(self) -> list[str]:
        """Mount targets for this device only."""
        if self.mountpoints:
            return list(self.mountpoints)
        if self.mountpoint:
            return [self.mountpoint]
        return []

    def all_mountpoints(self) -> list[str]:
        """Collect mountpoints on this device and all descendants."""
        result: list[str] = list(self.effective_mountpoints())
        for child in self.children:
            result.extend(child.all_mountpoints())
        return result

    def walk(self) -> list[BlockDevice]:
        """Depth-first list of this node and descendants."""
        out = [self]
        for child in self.children:
            out.extend(child.walk())
        return out

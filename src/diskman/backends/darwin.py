"""macOS backend: diskutil inventory, mount/unmount, eraseVolume/eraseDisk format."""

from __future__ import annotations

import plistlib
import re
import shutil
import subprocess
from typing import Any, Optional

from diskman.backends.common import ActionResult, run_cmd, run_privileged_darwin
from diskman.models import BlockDevice
from diskman.safety import can_format, can_mount, can_unmount

# diskutil eraseVolume / eraseDisk filesystem identifiers
# Prefer human labels shown in the UI; map to diskutil names.
DARWIN_FILESYSTEMS: dict[str, str] = {
    "APFS": "APFS",
    "JHFS+": "JHFS+",
    "ExFAT": "ExFAT",
    "MS-DOS FAT32": "MS-DOS FAT32",
    "Free Space": "Free Space",
}

# Content / filesystem name → short display fstype
_CONTENT_TO_FSTYPE = {
    "apple_apfs": "APFS",
    "apfs": "APFS",
    "apple_hfs": "HFS+",
    "hfs": "HFS+",
    "hfs+": "HFS+",
    "jhfs+": "JHFS+",
    "efi": "EFI",
    "apple_boot": "boot",
    "apple_corestorage": "CoreStorage",
    "microsoft basic data": "NTFS/exFAT",
    "windows_ntfs": "NTFS",
    "exfat": "ExFAT",
    "ms-dos": "FAT",
    "ms-dos fat16": "FAT16",
    "ms-dos fat32": "FAT32",
    "linux": "Linux",
    "linux_filesystem": "Linux",
}


def _diskutil_plist(*args: str) -> dict[str, Any]:
    if not shutil.which("diskutil"):
        raise RuntimeError("diskutil not found (macOS only)")
    cmd = ["diskutil", *args]
    try:
        proc = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            timeout=60,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("diskutil not found") from exc
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or exc.stdout or b"").decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"diskutil {' '.join(args)} failed: {err or exc.returncode}") from exc
    try:
        data = plistlib.loads(proc.stdout)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Failed to parse diskutil plist: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError("Unexpected diskutil plist type")
    return data


def _ident_to_path(ident: str) -> str:
    ident = (ident or "").strip()
    if not ident:
        return ""
    if ident.startswith("/dev/"):
        return ident
    return f"/dev/{ident}"


def _ident_to_name(ident: str) -> str:
    ident = (ident or "").strip()
    if ident.startswith("/dev/"):
        return ident[len("/dev/") :]
    return ident


def _normalize_fstype(content: Optional[str], filesystem_name: Optional[str] = None) -> Optional[str]:
    for raw in (filesystem_name, content):
        if not raw:
            continue
        key = str(raw).strip().lower()
        if key in _CONTENT_TO_FSTYPE:
            return _CONTENT_TO_FSTYPE[key]
        # Pass through short names
        if key in ("apfs", "exfat", "ntfs", "hfs+", "jhfs+"):
            return raw.strip()
        if key and key not in ("", "none", "apple_partition_map", "guid_partition_scheme"):
            return str(raw).strip()
    return None


def _info_device(ident: str) -> dict[str, Any]:
    try:
        return _diskutil_plist("info", "-plist", ident)
    except RuntimeError:
        return {}


def _dev_from_info(ident: str, info: dict[str, Any], *, dev_type: str, pkname: Optional[str] = None) -> BlockDevice:
    name = _ident_to_name(ident)
    path = info.get("DeviceNode") or _ident_to_path(ident)
    size = info.get("TotalSize") or info.get("Size")
    if size is not None:
        try:
            size = int(size)
        except (TypeError, ValueError):
            size = None

    content = info.get("Content") or info.get("PartitionType") or None
    fs_name = info.get("FilesystemName") or info.get("FilesystemType") or None
    fstype = _normalize_fstype(
        str(content) if content else None,
        str(fs_name) if fs_name else None,
    )

    mountpoint = info.get("MountPoint") or None
    if isinstance(mountpoint, str) and not mountpoint.strip():
        mountpoint = None

    label = info.get("VolumeName") or info.get("MediaName") or None
    if isinstance(label, str) and not label.strip():
        label = None

    uuid = info.get("VolumeUUID") or info.get("DiskUUID") or info.get("PartitionUUID") or None

    model = info.get("MediaName") or info.get("IORegistryEntryName") or None
    # Prefer hardware model for whole disks
    if info.get("MediaType") or info.get("BusProtocol"):
        model = info.get("IORegistryEntryName") or info.get("MediaName") or model

    serial = info.get("IORegistryEntrySerialNumber") or info.get("DeviceIdentifier")
    if serial == name:
        serial = None

    bus = info.get("BusProtocol") or info.get("SolidState")  # may be bool for SSD
    transport = None
    if isinstance(info.get("BusProtocol"), str):
        transport = info["BusProtocol"]
    elif info.get("Internal") is True:
        transport = "internal"
    elif info.get("Internal") is False:
        transport = "external"

    removable = info.get("Removable") or info.get("RemovableMedia") or info.get("Ejectable")
    if isinstance(removable, bool):
        pass
    else:
        removable = bool(removable) if removable is not None else None

    hotplug = info.get("Ejectable")
    if not isinstance(hotplug, bool):
        hotplug = removable

    rotational = None
    if "SolidState" in info:
        rotational = not bool(info.get("SolidState"))

    # Virtual / synthesized disks (APFS containers, disk images)
    virtual_or_physical = str(info.get("VirtualOrPhysical") or "").lower()
    is_virtual_media = virtual_or_physical == "virtual"
    is_disk_image = bool(info.get("DiskImageRemotePath") or info.get("ParentWholeDisk") == "disk image")

    # Refine type
    if dev_type == "disk" and info.get("WholeDisk") is False:
        dev_type = "part"
    content_l = str(content or "").lower()
    if "apfs container" in content_l or content_l == "apple_apfs_container":
        dev_type = "container"
    if info.get("APFSContainerReference") and info.get("WholeDisk") is False:
        # leaf APFS volume often still WholeDisk=false under container
        if info.get("FilesystemType") or info.get("MountPoint") is not None:
            if "volume" in str(info.get("MediaType") or "").lower() or info.get("VolumeName"):
                dev_type = "part"

    # System role volumes
    roles = info.get("APFSVolumeGroupRole") or info.get("SystemRoles") or []
    if isinstance(roles, str):
        roles = [roles]
    parttypename = None
    if roles:
        parttypename = ",".join(str(r) for r in roles)
    elif content:
        parttypename = str(content)

    # Force virtual flag via name prefix convention used by models.is_virtual
    # for synthesized/virtual media that should not be casually formatted.
    virtual_hint = is_virtual_media or is_disk_image

    mountpoints: list[str] = []
    if mountpoint:
        mountpoints.append(mountpoint)

    # Swap-like: APFS VM volume
    if label and label.upper() == "VM" and "System/Volumes/VM" in (mountpoint or ""):
        if "[SWAP]" not in mountpoints:
            mountpoints.append("[SWAP]")
        if not fstype:
            fstype = "swap"

    # macOS virtual devices: mark via dev_type for safety
    if virtual_hint and dev_type == "disk":
        # Keep as disk for tree display, but models.is_virtual also checks name
        pass

    return BlockDevice(
        name=name,
        path=str(path),
        size=size,
        dev_type=dev_type,
        fstype=fstype,
        mountpoint=mountpoint,
        label=str(label) if label else None,
        uuid=str(uuid) if uuid else None,
        model=str(model).strip() if model else None,
        serial=str(serial) if serial else None,
        transport=str(transport) if transport else None,
        rotational=rotational,
        removable=removable if isinstance(removable, bool) else None,
        hotplug=hotplug if isinstance(hotplug, bool) else None,
        vendor=None,
        state="mounted" if mountpoint else None,
        pkname=pkname,
        parttype=str(content) if content else None,
        parttypename=parttypename,
        partuuid=str(info.get("PartitionUUID") or "") or None,
        pttype=str(info.get("Content") or "") if info.get("WholeDisk") else None,
        fsavail=None,
        fsuse_pct=None,
        fssize=size if mountpoint else None,
        mountpoints=mountpoints,
        children=[],
        # Extra markers used by safety/models via name heuristics + fields
    )


def _partition_entry_to_device(entry: dict[str, Any], parent_ident: str) -> BlockDevice:
    ident = entry.get("DeviceIdentifier") or ""
    info = _info_device(ident) if ident else {}
    # Merge list-entry fields when info is sparse
    if not info.get("TotalSize") and entry.get("Size") is not None:
        info.setdefault("TotalSize", entry.get("Size"))
    if not info.get("Content") and entry.get("Content"):
        info.setdefault("Content", entry.get("Content"))
    if not info.get("VolumeName") and entry.get("VolumeName"):
        info.setdefault("VolumeName", entry.get("VolumeName"))
    if not info.get("MountPoint") and entry.get("MountPoint"):
        info.setdefault("MountPoint", entry.get("MountPoint"))

    dev = _dev_from_info(ident, info, dev_type="part", pkname=_ident_to_name(parent_ident))

    # Nested APFS volumes listed under a partition (older list layout)
    apfs_vols = entry.get("APFSVolumes") or []
    for vol in apfs_vols:
        if not isinstance(vol, dict):
            continue
        v_ident = vol.get("DeviceIdentifier") or ""
        if not v_ident:
            continue
        v_info = _info_device(v_ident)
        if not v_info.get("TotalSize") and vol.get("Size") is not None:
            v_info.setdefault("TotalSize", vol.get("Size"))
        if not v_info.get("VolumeName") and vol.get("VolumeName"):
            v_info.setdefault("VolumeName", vol.get("VolumeName"))
        if not v_info.get("MountPoint") and vol.get("MountPoint"):
            v_info.setdefault("MountPoint", vol.get("MountPoint"))
        child = _dev_from_info(
            v_ident,
            v_info,
            dev_type="part",
            pkname=dev.name,
        )
        dev.children.append(child)

    return dev


def _build_tree() -> list[BlockDevice]:
    listing = _diskutil_plist("list", "-plist")
    top = listing.get("AllDisksAndPartitions") or []
    devices: list[BlockDevice] = []

    for entry in top:
        if not isinstance(entry, dict):
            continue
        ident = entry.get("DeviceIdentifier") or ""
        if not ident:
            continue
        info = _info_device(ident)
        if not info.get("TotalSize") and entry.get("Size") is not None:
            info.setdefault("TotalSize", entry.get("Size"))
        if not info.get("Content") and entry.get("Content"):
            info.setdefault("Content", entry.get("Content"))

        disk = _dev_from_info(ident, info, dev_type="disk", pkname=None)

        # Standard partitions
        for part in entry.get("Partitions") or []:
            if isinstance(part, dict):
                disk.children.append(_partition_entry_to_device(part, ident))

        # APFS volumes directly on this whole-disk entry (container disks)
        for vol in entry.get("APFSVolumes") or []:
            if not isinstance(vol, dict):
                continue
            v_ident = vol.get("DeviceIdentifier") or ""
            if not v_ident:
                continue
            v_info = _info_device(v_ident)
            if not v_info.get("TotalSize") and vol.get("Size") is not None:
                v_info.setdefault("TotalSize", vol.get("Size"))
            if not v_info.get("VolumeName") and vol.get("VolumeName"):
                v_info.setdefault("VolumeName", vol.get("VolumeName"))
            if not v_info.get("MountPoint") and vol.get("MountPoint"):
                v_info.setdefault("MountPoint", vol.get("MountPoint"))
            disk.children.append(
                _dev_from_info(v_ident, v_info, dev_type="part", pkname=disk.name)
            )

        devices.append(disk)

    return devices


def _diskutil_device_arg(dev: BlockDevice) -> str:
    """Prefer identifier without /dev/ for diskutil (accepts both)."""
    name = (dev.name or "").strip()
    if name:
        return name
    path = (dev.path or "").strip()
    if path.startswith("/dev/"):
        return path[len("/dev/") :]
    return path


class DarwinBackend:
    name = "darwin"

    def list_devices(self) -> list[BlockDevice]:
        return _build_tree()

    def available_filesystems(self) -> list[str]:
        # All of these are built into diskutil on modern macOS
        return list(DARWIN_FILESYSTEMS.keys())

    def mount(self, dev: BlockDevice) -> ActionResult:
        check = can_mount(dev)
        if not check.allowed:
            return ActionResult(False, check.summary)

        arg = _diskutil_device_arg(dev)
        result = run_cmd(["diskutil", "mount", arg])
        if result.ok:
            msg = (result.stdout or result.message or "").strip() or f"Mounted {dev.path}"
            return ActionResult(True, msg, stdout=result.stdout, stderr=result.stderr)
        # Removable may need elevation rarely
        elevated = run_privileged_darwin(["diskutil", "mount", arg])
        if elevated.ok:
            msg = (elevated.stdout or elevated.message or "").strip() or f"Mounted {dev.path}"
            return ActionResult(True, msg, stdout=elevated.stdout, stderr=elevated.stderr)
        return elevated if elevated.message else result

    def unmount(self, dev: BlockDevice) -> ActionResult:
        check = can_unmount(dev)
        if not check.allowed:
            return ActionResult(False, check.summary)

        arg = _diskutil_device_arg(dev)
        # unmount (not unmountDisk) for single volume; force only if needed later
        result = run_cmd(["diskutil", "unmount", arg])
        if result.ok:
            return ActionResult(
                True,
                (result.stdout or "").strip() or f"Unmounted {dev.path}",
                stdout=result.stdout,
                stderr=result.stderr,
            )
        elevated = run_privileged_darwin(["diskutil", "unmount", arg])
        if elevated.ok:
            return ActionResult(
                True,
                (elevated.stdout or "").strip() or f"Unmounted {dev.path}",
                stdout=elevated.stdout,
                stderr=elevated.stderr,
            )
        return elevated if elevated.message else result

    def format(
        self,
        dev: BlockDevice,
        fstype: str,
        label: Optional[str],
        *,
        confirm_name: str,
    ) -> ActionResult:
        if confirm_name.strip() != dev.name:
            return ActionResult(False, f"Confirmation mismatch: type '{dev.name}' exactly")

        check = can_format(dev)
        if not check.allowed:
            return ActionResult(False, check.summary)

        if fstype not in DARWIN_FILESYSTEMS:
            return ActionResult(
                False,
                f"Unsupported filesystem on macOS: {fstype}. "
                f"Choose one of: {', '.join(DARWIN_FILESYSTEMS)}",
            )

        fs_id = DARWIN_FILESYSTEMS[fstype]
        vol_name = (label or "").strip() or "Untitled"
        # FAT labels are short
        if "FAT" in fs_id.upper() or fs_id == "ExFAT":
            vol_name = re.sub(r"[^A-Za-z0-9 _-]", "", vol_name)[:11] or "UNTITLED"

        arg = _diskutil_device_arg(dev)

        if dev.is_disk and not dev.children:
            # Empty whole disk
            cmd = ["diskutil", "eraseDisk", fs_id, vol_name, arg]
        elif dev.is_disk and dev.children:
            # Whole-disk erase (destroys partition map) — safety already warned
            cmd = ["diskutil", "eraseDisk", fs_id, vol_name, arg]
        else:
            # Partition / volume
            cmd = ["diskutil", "eraseVolume", fs_id, vol_name, arg]

        result = run_privileged_darwin(cmd)
        if not result.ok:
            return ActionResult(
                False,
                f"Format failed: {result.message}",
                stdout=result.stdout,
                stderr=result.stderr,
                returncode=result.returncode,
            )

        msg = f"Formatted {dev.path} as {fstype}"
        if vol_name:
            msg += f' label="{vol_name}"'
        return ActionResult(
            True,
            msg,
            stdout=result.stdout,
            stderr=result.stderr,
            returncode=result.returncode,
        )

    def privilege_hint(self) -> str:
        return "auth via sudo -n or macOS admin dialog"

"""Discover block devices via lsblk."""

from __future__ import annotations

import json
import re
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

from diskman.models import BlockDevice, human_size

LSBLK_COLUMNS = (
    "NAME,PATH,SIZE,TYPE,FSTYPE,MOUNTPOINT,LABEL,UUID,"
    "MODEL,SERIAL,TRAN,ROTA,RM,HOTPLUG,VENDOR,STATE,PKNAME,"
    "PARTTYPE,PARTTYPENAME,PARTUUID,PTTYPE,FSAVAIL,FSUSE%,FSSIZE"
)

# /dev/nvme0n1p1 or /dev/sda1[/@home] style sources
_SOURCE_DEV_RE = re.compile(r"^(/dev/\S+?)(?:\[.*\])?$")


def _parse_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_bool(value: Any) -> Optional[bool]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    s = str(value).strip().lower()
    if s in ("1", "true", "yes"):
        return True
    if s in ("0", "false", "no"):
        return False
    return None


def _from_lsblk_node(node: dict[str, Any]) -> BlockDevice:
    path = node.get("path") or ""
    name = node.get("name") or ""
    if not path and name:
        path = f"/dev/{name}"

    children_raw = node.get("children") or []
    children = [_from_lsblk_node(c) for c in children_raw]

    return BlockDevice(
        name=name,
        path=path,
        size=_parse_int(node.get("size")),
        dev_type=(node.get("type") or "disk").lower(),
        fstype=node.get("fstype") or None,
        mountpoint=node.get("mountpoint") or None,
        label=node.get("label") or None,
        uuid=node.get("uuid") or None,
        model=(node.get("model") or None),
        serial=(node.get("serial") or None),
        transport=node.get("tran") or None,
        rotational=_parse_bool(node.get("rota")),
        removable=_parse_bool(node.get("rm")),
        hotplug=_parse_bool(node.get("hotplug")),
        vendor=(node.get("vendor") or None),
        state=node.get("state") or None,
        pkname=node.get("pkname") or None,
        parttype=node.get("parttype") or None,
        parttypename=node.get("parttypename") or None,
        partuuid=node.get("partuuid") or None,
        pttype=node.get("pttype") or None,
        fsavail=_parse_int(node.get("fsavail")),
        fsuse_pct=node.get("fsuse%") or node.get("fsuse_pct") or None,
        fssize=_parse_int(node.get("fssize")),
        children=children,
    )


def _read_proc_mounts() -> dict[str, list[str]]:
    """Map resolved /dev path -> list of mount targets from /proc/mounts."""
    mapping: dict[str, list[str]] = defaultdict(list)
    try:
        text = Path("/proc/mounts").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}

    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        source, target = parts[0], parts[1]
        if not source.startswith("/dev/"):
            continue
        # Strip btrfs subvol suffix shown by some tools; /proc/mounts is plain path
        m = _SOURCE_DEV_RE.match(source)
        dev_path = m.group(1) if m else source
        try:
            dev_path = str(Path(dev_path).resolve())
        except OSError:
            pass
        # Unescape octal sequences in mount target (e.g. \040 for space)
        target = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), target)
        if target not in mapping[dev_path]:
            mapping[dev_path].append(target)
    return mapping


def _read_swaps() -> set[str]:
    """Return device paths that are active swap."""
    swaps: set[str] = set()
    try:
        lines = Path("/proc/swaps").read_text(encoding="utf-8", errors="replace").splitlines()[1:]
    except OSError:
        return swaps
    for line in lines:
        parts = line.split()
        if not parts:
            continue
        path = parts[0]
        if path.startswith("/dev/"):
            try:
                swaps.add(str(Path(path).resolve()))
            except OSError:
                swaps.add(path)
    return swaps


def _enrich_mounts(dev: BlockDevice, mounts: dict[str, list[str]], swaps: set[str]) -> None:
    path = dev.path or ""
    try:
        resolved = str(Path(path).resolve()) if path else ""
    except OSError:
        resolved = path

    found: list[str] = []
    if resolved and resolved in mounts:
        found.extend(mounts[resolved])
    if path and path in mounts and path != resolved:
        for mp in mounts[path]:
            if mp not in found:
                found.append(mp)

    # Prefer lsblk single mountpoint if somehow missing from /proc/mounts
    if dev.mountpoint and dev.mountpoint not in found:
        found.insert(0, dev.mountpoint)

    if resolved in swaps or path in swaps:
        if "[SWAP]" not in found:
            found.append("[SWAP]")
        if not dev.fstype:
            dev.fstype = "swap"

    dev.mountpoints = found
    # Prefer showing / when this device hosts the root filesystem
    if "/" in found:
        dev.mountpoint = "/"
    elif found and not dev.mountpoint:
        dev.mountpoint = found[0]
    elif found and dev.mountpoint not in found:
        dev.mountpoint = found[0]

    for child in dev.children:
        _enrich_mounts(child, mounts, swaps)


def list_devices() -> list[BlockDevice]:
    """Return top-level block devices from lsblk JSON."""
    cmd = ["lsblk", "-J", "-b", "-o", LSBLK_COLUMNS]
    try:
        proc = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("lsblk not found on PATH") from exc
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or exc.stdout or "").strip()
        raise RuntimeError(f"lsblk failed: {err or exc.returncode}") from exc

    data = json.loads(proc.stdout or "{}")
    blockdevices = data.get("blockdevices") or []
    devices = [_from_lsblk_node(n) for n in blockdevices]
    mounts = _read_proc_mounts()
    swaps = _read_swaps()
    for d in devices:
        _enrich_mounts(d, mounts, swaps)
    return devices


def find_device(devices: list[BlockDevice], name_or_path: str) -> Optional[BlockDevice]:
    """Find a device by name (sda1) or path (/dev/sda1)."""
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
            # depth from pkname chain is approximate; indent by path segments of name
            if dev.pkname:
                depth = 1
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

"""Safety policy for mount, unmount, and format operations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from diskman.models import BlockDevice
from diskman.platform import get_platform

# Mountpoints that must never be unmounted or formatted over (POSIX + macOS).
_PROTECTED_COMMON = frozenset(
    {
        "/",
        "/boot",
        "/boot/efi",
        "/efi",
        "/usr",
        "/var",
        "/home",
        "/nix",
        "/ostree",
        "/root",
        "/opt",
        "/bin",
        "/sbin",
        "/lib",
        "/lib64",
        "/etc",
    }
)

_PROTECTED_DARWIN = frozenset(
    {
        "/System",
        "/System/Volumes/Data",
        "/System/Volumes/Preboot",
        "/System/Volumes/VM",
        "/System/Volumes/Update",
        "/System/Volumes/iSCPreboot",
        "/System/Volumes/Hardware",
        "/Library",
        "/Users",
        "/Applications",
        "/private",
        "/private/var",
        "/cores",
        "/Volumes/Macintosh HD",
        "/Volumes/Macintosh HD - Data",
    }
)

# Volume labels that are always system-critical on macOS
_PROTECTED_VOLUME_LABELS_DARWIN = frozenset(
    {
        "macintosh hd",
        "macintosh hd - data",
        "preboot",
        "recovery",
        "vm",
        "update",
        "xarts",
        "iscpreboot",
        "hardware",
        "iSCPreboot".lower(),
    }
)


def protected_mountpoints() -> frozenset[str]:
    base = set(_PROTECTED_COMMON)
    if get_platform() == "darwin":
        base |= _PROTECTED_DARWIN
    return frozenset(base)


@dataclass(frozen=True)
class SafetyResult:
    allowed: bool
    reasons: list[str]
    warnings: list[str]

    @property
    def summary(self) -> str:
        parts: list[str] = []
        if self.reasons:
            parts.append("Blocked: " + "; ".join(self.reasons))
        if self.warnings:
            parts.append("Warning: " + "; ".join(self.warnings))
        return " | ".join(parts) if parts else "OK"


def _normalize_mountpoint(mp: Optional[str]) -> Optional[str]:
    if not mp or mp == "[SWAP]":
        return mp
    try:
        return str(Path(mp).resolve())
    except OSError:
        return mp


def _is_protected_mount(mp: Optional[str]) -> bool:
    if not mp:
        return False
    if mp == "[SWAP]":
        return True
    norm = _normalize_mountpoint(mp) or mp
    protected = protected_mountpoints()
    if norm in protected:
        return True
    for p in protected:
        if norm == p:
            return True
        if p != "/" and norm.startswith(p + "/"):
            if p in (
                "/boot",
                "/usr",
                "/home",
                "/nix",
                "/ostree",
                "/efi",
                "/System",
                "/Library",
                "/Users",
                "/Applications",
                "/private",
            ):
                return True
    # macOS: anything under /System is sacred
    if get_platform() == "darwin" and (
        norm == "/System" or norm.startswith("/System/")
    ):
        return True
    return False


def _collect_mount_issues(dev: BlockDevice) -> list[str]:
    """Reasons derived from this device's mount table."""
    reasons: list[str] = []
    mps = dev.effective_mountpoints()
    for mp in mps:
        if mp == "[SWAP]":
            reasons.append("Device is active swap / VM volume")
            continue
        if _is_protected_mount(mp):
            reasons.append(f"Protected mountpoint: {mp}")
        elif mp == "/":
            reasons.append("Device hosts root filesystem (/)")
    return reasons


def _device_path_ok(dev: BlockDevice) -> Optional[str]:
    path = (dev.path or "").strip()
    if not path.startswith("/dev/"):
        return "Device path is not under /dev/"
    name = Path(path).name
    if not name or name in (".", "..") or "/" in name:
        return "Invalid device name"
    # On macOS, device nodes can disappear when unmounted/ejected; still allow
    # operations by identifier if path missing — but prefer existing nodes.
    if not Path(path).exists():
        # diskutil accepts names even if node is temporarily gone; soft-warn via reason only for Linux
        if get_platform() == "linux":
            return f"Device path does not exist: {path}"
    return None


def _darwin_system_volume(dev: BlockDevice) -> Optional[str]:
    """Extra macOS guards for system volumes / containers."""
    if get_platform() != "darwin":
        return None

    label = (dev.label or "").strip().lower()
    if label in _PROTECTED_VOLUME_LABELS_DARWIN:
        return f"System volume label '{dev.label}' cannot be formatted"

    # Roles from APFS (stored in parttypename as comma-joined roles when present)
    roles = (dev.parttypename or "").lower()
    for role in ("system", "preboot", "recovery", "vm", "update", "hardware", "xart"):
        if role in roles.split(","):
            return f"APFS system role volume ({role}) cannot be formatted"

    fstype = (dev.fstype or "").upper()
    if fstype == "EFI" or (dev.parttype or "").upper() == "EFI":
        return "EFI system partition cannot be formatted"

    # Never format the whole internal boot disk when it hosts /
    if dev.is_disk:
        for mp in dev.all_mountpoints():
            if _is_protected_mount(mp) or mp == "/":
                return f"Disk hosts protected mount {mp}"

    return None


def can_format(dev: BlockDevice) -> SafetyResult:
    """Return whether formatting this device is allowed."""
    reasons: list[str] = []
    warnings: list[str] = []

    path_err = _device_path_ok(dev)
    if path_err:
        reasons.append(path_err)

    if dev.is_virtual:
        reasons.append(f"Virtual device ({dev.dev_type or dev.name}) cannot be formatted")

    if dev.is_swap:
        reasons.append("Active or swap-type device cannot be formatted")

    mount_issues = _collect_mount_issues(dev)
    reasons.extend(mount_issues)
    real_mps = [m for m in dev.effective_mountpoints() if m and m != "[SWAP]"]
    if real_mps and not mount_issues:
        shown = ", ".join(real_mps[:4])
        extra = f" (+{len(real_mps) - 4} more)" if len(real_mps) > 4 else ""
        reasons.append(f"Device is mounted at {shown}{extra}")

    for child in dev.walk()[1:]:
        child_issues = _collect_mount_issues(child)
        for issue in child_issues:
            reasons.append(f"Child {child.name}: {issue}")
        child_mps = [m for m in child.effective_mountpoints() if m and m != "[SWAP]"]
        if child_mps and not child_issues:
            reasons.append(f"Child {child.name} is mounted at {child_mps[0]}")
        if child.is_swap:
            reasons.append(f"Child {child.name} is swap")

    darwin_block = _darwin_system_volume(dev)
    if darwin_block:
        reasons.append(darwin_block)

    if dev.is_disk and dev.children:
        warnings.append(
            f"Whole-disk format of {dev.name} will destroy all {len(dev.children)} partition(s)/volume(s)"
        )

    if not dev.removable and not dev.hotplug and not dev.is_virtual:
        warnings.append("Internal (non-removable) device")

    if dev.size is not None and dev.size >= 100 * 1024**3:
        warnings.append(f"Large device ({dev.size_human})")

    if dev.fstype:
        warnings.append(f"Existing filesystem {dev.fstype} will be destroyed")
    if dev.label:
        warnings.append(f"Existing label '{dev.label}' will be destroyed")

    seen: set[str] = set()
    uniq_reasons: list[str] = []
    for r in reasons:
        if r not in seen:
            seen.add(r)
            uniq_reasons.append(r)

    return SafetyResult(
        allowed=len(uniq_reasons) == 0,
        reasons=uniq_reasons,
        warnings=warnings,
    )


def can_mount(dev: BlockDevice) -> SafetyResult:
    reasons: list[str] = []
    warnings: list[str] = []

    path_err = _device_path_ok(dev)
    if path_err:
        reasons.append(path_err)

    if not dev.is_partition and dev.dev_type not in ("part", "disk", "container"):
        if not dev.fstype:
            reasons.append("Not a mountable partition")

    # Linux needs a detected fstype. macOS diskutil can mount by identifier
    # when a volume name exists even if filesystem metadata is sparse.
    if not dev.fstype:
        if get_platform() == "darwin":
            if not dev.label and not dev.is_partition:
                reasons.append("No filesystem detected")
        else:
            reasons.append("No filesystem detected")

    if dev.is_mounted:
        reasons.append(f"Already mounted at {dev.mountpoint}")
    if dev.is_swap:
        reasons.append("Swap / VM volumes are not mounted via this action")
    if dev.is_virtual and not dev.fstype:
        reasons.append("Virtual device without filesystem")

    return SafetyResult(allowed=len(reasons) == 0, reasons=reasons, warnings=warnings)


def can_unmount(dev: BlockDevice) -> SafetyResult:
    reasons: list[str] = []
    warnings: list[str] = []

    path_err = _device_path_ok(dev)
    if path_err:
        reasons.append(path_err)

    if not dev.is_mounted and not dev.is_swap:
        reasons.append("Device is not mounted")

    for mp in dev.effective_mountpoints():
        if _is_protected_mount(mp) or mp == "/":
            reasons.append(f"Refusing to unmount protected path: {mp}")

    real_mps = [m for m in dev.effective_mountpoints() if m and m != "[SWAP]"]
    if len(real_mps) > 1:
        reasons.append(
            f"Device has {len(real_mps)} mountpoints (including system subvolumes); unmount refused"
        )

    if dev.is_swap:
        reasons.append("Swap / VM is not unmounted via this action")

    # macOS system volume labels
    if get_platform() == "darwin":
        label = (dev.label or "").strip().lower()
        if label in _PROTECTED_VOLUME_LABELS_DARWIN:
            reasons.append(f"Refusing to unmount system volume '{dev.label}'")

    return SafetyResult(allowed=len(reasons) == 0, reasons=reasons, warnings=warnings)


def confirm_name_matches(dev: BlockDevice, typed: str) -> bool:
    """True if user typed the device basename exactly."""
    return typed.strip() == dev.name

"""Safety policy for mount, unmount, and format operations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from diskman.models import BlockDevice

# Mountpoints that must never be unmounted or formatted over.
PROTECTED_MOUNTPOINTS = frozenset(
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
    }
)


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
    if norm in PROTECTED_MOUNTPOINTS:
        return True
    # Protect common system prefixes when they appear as mount targets
    for protected in PROTECTED_MOUNTPOINTS:
        if norm == protected:
            return True
        # e.g. /var/log is under protected /var intent when /var itself isn't separate
        if protected != "/" and (norm.startswith(protected + "/")):
            # Only treat direct children of protected system roots as sensitive
            # when the protected path is a well-known system dir.
            if protected in ("/boot", "/usr", "/home", "/nix", "/ostree", "/efi"):
                return True
    return False


def _collect_mount_issues(dev: BlockDevice) -> list[str]:
    """Reasons derived from this device's mount table (all subvolume mounts)."""
    reasons: list[str] = []
    mps = dev.effective_mountpoints()
    for mp in mps:
        if mp == "[SWAP]":
            reasons.append("Device is active swap")
            continue
        if _is_protected_mount(mp):
            reasons.append(f"Protected mountpoint: {mp}")
        elif mp == "/":
            reasons.append("Device hosts root filesystem (/)")
    # Any mount means "is mounted" for format
    real_mps = [m for m in mps if m and m != "[SWAP]"]
    if real_mps and not any(r.startswith("Protected") or "root filesystem" in r for r in reasons):
        # still report mounted for format path via caller
        pass
    return reasons


def _device_path_ok(dev: BlockDevice) -> Optional[str]:
    path = (dev.path or "").strip()
    if not path.startswith("/dev/"):
        return "Device path is not under /dev/"
    # Reject path traversal / weird names
    name = Path(path).name
    if not name or name in (".", "..") or "/" in name:
        return "Invalid device name"
    if not Path(path).exists():
        return f"Device path does not exist: {path}"
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

    # Self mounts (including all btrfs subvolume mounts from /proc/mounts)
    mount_issues = _collect_mount_issues(dev)
    reasons.extend(mount_issues)
    real_mps = [m for m in dev.effective_mountpoints() if m and m != "[SWAP]"]
    if real_mps and not mount_issues:
        shown = ", ".join(real_mps[:4])
        extra = f" (+{len(real_mps) - 4} more)" if len(real_mps) > 4 else ""
        reasons.append(f"Device is mounted at {shown}{extra}")

    # Children mounted or protected
    for child in dev.walk()[1:]:  # skip self
        child_issues = _collect_mount_issues(child)
        for issue in child_issues:
            reasons.append(f"Child {child.name}: {issue}")
        child_mps = [m for m in child.effective_mountpoints() if m and m != "[SWAP]"]
        if child_mps and not child_issues:
            reasons.append(f"Child {child.name} is mounted at {child_mps[0]}")
        if child.is_swap:
            reasons.append(f"Child {child.name} is swap")

    # Whole-disk with partitions: allow only if no children blocked and user confirms
    if dev.is_disk and dev.children:
        warnings.append(
            f"Whole-disk format of {dev.name} will destroy all {len(dev.children)} partition(s)"
        )

    # Soft warnings
    if not dev.removable and not dev.hotplug and not dev.is_virtual:
        warnings.append("Internal (non-removable) device")

    if dev.size is not None and dev.size >= 100 * 1024**3:
        warnings.append(f"Large device ({dev.size_human})")

    if dev.fstype:
        warnings.append(f"Existing filesystem {dev.fstype} will be destroyed")
    if dev.label:
        warnings.append(f"Existing label '{dev.label}' will be destroyed")

    # Dedupe reasons while preserving order
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

    if not dev.is_partition and dev.dev_type not in ("part", "disk"):
        # Allow partition primarily; whole disk with fs is rare but possible
        if not dev.fstype:
            reasons.append("Not a mountable partition")

    if not dev.fstype:
        reasons.append("No filesystem detected")
    if dev.is_mounted:
        reasons.append(f"Already mounted at {dev.mountpoint}")
    if dev.is_swap:
        reasons.append("Swap devices are not mounted via udisks")
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

    # Multiple mounts (typical btrfs system volume) — too risky for one-shot unmount
    real_mps = [m for m in dev.effective_mountpoints() if m and m != "[SWAP]"]
    if len(real_mps) > 1:
        reasons.append(
            f"Device has {len(real_mps)} mountpoints (including system subvolumes); unmount refused"
        )

    if dev.is_swap:
        reasons.append("Swap is not unmounted via this action")

    return SafetyResult(allowed=len(reasons) == 0, reasons=reasons, warnings=warnings)


def confirm_name_matches(dev: BlockDevice, typed: str) -> bool:
    """True if user typed the device basename exactly."""
    return typed.strip() == dev.name

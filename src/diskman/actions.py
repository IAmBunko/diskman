"""Mount, unmount, and format block devices via system tools."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from typing import Optional

from diskman.models import BlockDevice
from diskman.safety import SafetyResult, can_format, can_mount, can_unmount

# Filesystem id -> (binary name, build_args(path, label) -> argv)
MkfsBuilder = Callable[[str, Optional[str]], list[str]]
FILESYSTEMS: dict[str, tuple[str, MkfsBuilder]] = {}


def _reg(fs: str, binary: str):
    def decorator(fn: MkfsBuilder) -> MkfsBuilder:
        FILESYSTEMS[fs] = (binary, fn)
        return fn

    return decorator


@_reg("ext4", "mkfs.ext4")
def _mkfs_ext4(path: str, label: Optional[str]) -> list[str]:
    cmd = ["mkfs.ext4", "-F"]
    if label:
        cmd.extend(["-L", label[:16]])
    cmd.append(path)
    return cmd


@_reg("xfs", "mkfs.xfs")
def _mkfs_xfs(path: str, label: Optional[str]) -> list[str]:
    cmd = ["mkfs.xfs", "-f"]
    if label:
        cmd.extend(["-L", label[:12]])
    cmd.append(path)
    return cmd


@_reg("btrfs", "mkfs.btrfs")
def _mkfs_btrfs(path: str, label: Optional[str]) -> list[str]:
    cmd = ["mkfs.btrfs", "-f"]
    if label:
        cmd.extend(["-L", label[:255]])
    cmd.append(path)
    return cmd


@_reg("f2fs", "mkfs.f2fs")
def _mkfs_f2fs(path: str, label: Optional[str]) -> list[str]:
    cmd = ["mkfs.f2fs", "-f"]
    if label:
        cmd.extend(["-l", label[:512]])
    cmd.append(path)
    return cmd


@_reg("vfat", "mkfs.vfat")
def _mkfs_vfat(path: str, label: Optional[str]) -> list[str]:
    cmd = ["mkfs.vfat", "-F", "32"]
    if label:
        # FAT labels: max 11 chars, typically uppercase
        cmd.extend(["-n", label.upper()[:11]])
    cmd.append(path)
    return cmd


@_reg("exfat", "mkfs.exfat")
def _mkfs_exfat(path: str, label: Optional[str]) -> list[str]:
    cmd = ["mkfs.exfat"]
    if label:
        cmd.extend(["-n", label[:15]])
    cmd.append(path)
    return cmd


def available_filesystems() -> list[str]:
    """Return FS types whose mkfs binary exists on PATH."""
    out: list[str] = []
    for fs, (binary, _) in FILESYSTEMS.items():
        if shutil.which(binary):
            out.append(fs)
    return out


@dataclass
class ActionResult:
    ok: bool
    message: str
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0


def _run(cmd: list[str], timeout: int = 600) -> ActionResult:
    """Run a command without touching the TUI's controlling terminal.

    stdin is always DEVNULL so sudo/pkexec/mkfs cannot steal the TTY and
    tear down Textual's alternate screen.
    """
    try:
        proc = subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
            start_new_session=True,
        )
    except FileNotFoundError:
        return ActionResult(False, f"Command not found: {cmd[0]}")
    except subprocess.TimeoutExpired:
        return ActionResult(False, f"Timed out: {' '.join(cmd)}")
    except OSError as exc:
        return ActionResult(False, f"Failed to run {' '.join(cmd)}: {exc}")

    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    ok = proc.returncode == 0
    msg = (stderr or stdout or "").strip()
    if ok and not msg:
        msg = "OK"
    elif not ok and not msg:
        msg = f"Exit code {proc.returncode}"
    return ActionResult(ok, msg, stdout=stdout, stderr=stderr, returncode=proc.returncode)


def _sudo_needs_password(result: ActionResult) -> bool:
    text = f"{result.message}\n{result.stderr}\n{result.stdout}".lower()
    needles = (
        "a password is required",
        "password is required",
        "a terminal is required to read the password",
        "no tty present",
        "authentication is required",
        "is not in the sudoers file",
    )
    return any(n in text for n in needles)


def _run_privileged(cmd: list[str], timeout: int = 600) -> ActionResult:
    """Run command as root without interactive TTY password prompts.

    Order:
      1. sudo -n (passwordless / cached credentials)
      2. pkexec (desktop polkit dialog — does not use the terminal)

    Never falls back to interactive ``sudo`` — that steals stdin and kills the TUI.
    """
    last: Optional[ActionResult] = None

    if shutil.which("sudo"):
        result = _run(["sudo", "-n", "--", *cmd], timeout=timeout)
        if result.ok:
            return result
        last = result
        # If sudo actually ran the command and it failed, do not retry with pkexec
        # (would prompt again for the same failing operation).
        if not _sudo_needs_password(result) and "sudo:" not in (result.stderr or "").lower():
            return result

    if shutil.which("pkexec"):
        # --disable-internal-agent: never fall back to a TTY password prompt
        # (that would steal stdin and kill the Textual UI). Use the desktop
        # polkit agent instead, or fail with a clear message.
        result = _run(["pkexec", "--disable-internal-agent", *cmd], timeout=timeout)
        if result.ok:
            return result
        last = result
        hint = (
            "Privilege elevation cancelled or denied. "
            "Authenticate via the desktop dialog, or run `sudo -v` in another "
            "terminal to cache credentials, then retry."
        )
        detail = (result.message or result.stderr or "").strip()
        return ActionResult(
            False,
            f"{hint}" + (f" ({detail})" if detail else ""),
            stdout=result.stdout,
            stderr=result.stderr,
            returncode=result.returncode,
        )

    if last is not None and _sudo_needs_password(last):
        return ActionResult(
            False,
            "Root access required. Run `sudo -v` in another terminal to cache "
            "your password, then retry format. (Interactive sudo is disabled "
            "inside the TUI so it cannot steal the terminal.)",
            stdout=last.stdout,
            stderr=last.stderr,
            returncode=last.returncode,
        )

    return ActionResult(
        False,
        "Neither passwordless sudo nor pkexec is available for privilege elevation. "
        "Run `sudo -v` then retry, or install polkit/pkexec.",
    )


def mount_device(dev: BlockDevice) -> ActionResult:
    check = can_mount(dev)
    if not check.allowed:
        return ActionResult(False, check.summary)

    if not shutil.which("udisksctl"):
        return ActionResult(False, "udisksctl not found")

    result = _run(["udisksctl", "mount", "-b", dev.path])
    if result.ok:
        return ActionResult(
            True,
            result.stdout.strip() or result.message,
            stdout=result.stdout,
            stderr=result.stderr,
        )
    return result


def unmount_device(dev: BlockDevice) -> ActionResult:
    check = can_unmount(dev)
    if not check.allowed:
        return ActionResult(False, check.summary)

    if not shutil.which("udisksctl"):
        return ActionResult(False, "udisksctl not found")

    result = _run(["udisksctl", "unmount", "-b", dev.path])
    if result.ok:
        return ActionResult(
            True,
            result.stdout.strip() or f"Unmounted {dev.path}",
            stdout=result.stdout,
            stderr=result.stderr,
        )
    return result


def format_device(
    dev: BlockDevice,
    fstype: str,
    label: Optional[str] = None,
    *,
    confirm_name: str,
) -> ActionResult:
    """Wipe signatures and create a new filesystem. Requires exact name confirm."""
    try:
        return _format_device_impl(dev, fstype, label, confirm_name=confirm_name)
    except Exception as exc:  # noqa: BLE001 — surface any unexpected error to UI
        return ActionResult(False, f"Format error: {exc}")


def _format_device_impl(
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

    if fstype not in FILESYSTEMS:
        return ActionResult(False, f"Unsupported filesystem: {fstype}")

    binary, builder = FILESYSTEMS[fstype]
    if not shutil.which(binary):
        return ActionResult(False, f"{binary} not found on PATH")

    if not shutil.which("wipefs"):
        return ActionResult(False, "wipefs not found on PATH")

    wipe = _run_privileged(["wipefs", "-a", dev.path])
    if not wipe.ok:
        return ActionResult(
            False,
            f"wipefs failed: {wipe.message}",
            stdout=wipe.stdout,
            stderr=wipe.stderr,
            returncode=wipe.returncode,
        )

    clean_label = label.strip() if label else None
    mkfs_cmd = builder(dev.path, clean_label)
    mkfs = _run_privileged(mkfs_cmd)
    if not mkfs.ok:
        return ActionResult(
            False,
            f"mkfs failed: {mkfs.message}",
            stdout=(wipe.stdout or "") + (mkfs.stdout or ""),
            stderr=(wipe.stderr or "") + (mkfs.stderr or ""),
            returncode=mkfs.returncode,
        )

    msg = f"Formatted {dev.path} as {fstype}"
    if clean_label:
        msg += f' label="{clean_label}"'
    return ActionResult(
        True,
        msg,
        stdout=(wipe.stdout or "") + (mkfs.stdout or ""),
        stderr=(wipe.stderr or "") + (mkfs.stderr or ""),
    )


def describe_format_check(dev: BlockDevice) -> SafetyResult:
    return can_format(dev)

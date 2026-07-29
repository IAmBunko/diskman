"""Shared helpers for backends (subprocess runners, privilege elevation)."""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from typing import Optional


@dataclass
class ActionResult:
    ok: bool
    message: str
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0


def run_cmd(cmd: list[str], timeout: int = 600) -> ActionResult:
    """Run a command without touching the TUI's controlling terminal.

    stdin is always DEVNULL so sudo/pkexec/osascript/mkfs cannot steal the TTY
    and tear down Textual's alternate screen.
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


def sudo_needs_password(result: ActionResult) -> bool:
    text = f"{result.message}\n{result.stderr}\n{result.stdout}".lower()
    needles = (
        "a password is required",
        "password is required",
        "a terminal is required to read the password",
        "no tty present",
        "authentication is required",
        "is not in the sudoers file",
        "sorry, user",
    )
    return any(n in text for n in needles)


def run_privileged_linux(cmd: list[str], timeout: int = 600) -> ActionResult:
    """Elevate on Linux: sudo -n, then pkexec (desktop polkit)."""
    last: Optional[ActionResult] = None

    if shutil.which("sudo"):
        result = run_cmd(["sudo", "-n", "--", *cmd], timeout=timeout)
        if result.ok:
            return result
        last = result
        if not sudo_needs_password(result) and "sudo:" not in (result.stderr or "").lower():
            return result

    if shutil.which("pkexec"):
        result = run_cmd(
            ["pkexec", "--disable-internal-agent", *cmd],
            timeout=timeout,
        )
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

    if last is not None and sudo_needs_password(last):
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


def run_privileged_darwin(cmd: list[str], timeout: int = 600) -> ActionResult:
    """Elevate on macOS: try plain command, then sudo -n, then osascript admin dialog."""
    # Many diskutil ops on removable media work without elevation.
    direct = run_cmd(cmd, timeout=timeout)
    if direct.ok:
        return direct

    last = direct
    if shutil.which("sudo"):
        result = run_cmd(["sudo", "-n", "--", *cmd], timeout=timeout)
        if result.ok:
            return result
        last = result
        if not sudo_needs_password(result) and "sudo:" not in (result.stderr or "").lower():
            # Command ran as root and failed for a real reason
            return result

    if shutil.which("osascript"):
        shell = " ".join(shlex.quote(c) for c in cmd)
        # json.dumps produces a double-quoted AppleScript string literal
        script = f"do shell script {json.dumps(shell)} with administrator privileges"
        result = run_cmd(["osascript", "-e", script], timeout=timeout)
        if result.ok:
            return result
        last = result
        detail = (result.message or result.stderr or "").strip()
        if "user canceled" in detail.lower() or "cancelled" in detail.lower():
            return ActionResult(
                False,
                "Administrator authentication cancelled.",
                stdout=result.stdout,
                stderr=result.stderr,
                returncode=result.returncode,
            )
        return ActionResult(
            False,
            "Administrator privileges required. Approve the macOS password dialog, "
            "or run `sudo -v` in another terminal to cache credentials, then retry."
            + (f" ({detail})" if detail else ""),
            stdout=result.stdout,
            stderr=result.stderr,
            returncode=result.returncode,
        )

    if last is not None and sudo_needs_password(last):
        return ActionResult(
            False,
            "Root access required. Run `sudo -v` in another terminal to cache "
            "your password, then retry. (Interactive sudo is disabled inside the TUI.)",
            stdout=last.stdout,
            stderr=last.stderr,
            returncode=last.returncode,
        )

    return ActionResult(
        False,
        f"Operation failed: {last.message if last else 'unknown error'}",
        stdout=last.stdout if last else "",
        stderr=last.stderr if last else "",
        returncode=last.returncode if last else 1,
    )

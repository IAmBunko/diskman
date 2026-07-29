"""Format wizard modal with type-to-confirm safety."""

from __future__ import annotations

from typing import Optional

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, Static

from diskman.actions import ActionResult, available_filesystems, format_device, privilege_hint
from diskman.models import BlockDevice
from diskman.platform import get_platform
from diskman.safety import can_format, confirm_name_matches


class FormatModal(ModalScreen[bool]):
    """Modal to format a block device. Returns True if format succeeded."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True),
    ]

    DEFAULT_CSS = """
    FormatModal {
        align: center middle;
    }

    #format-dialog {
        width: 72;
        max-width: 90%;
        height: auto;
        max-height: 90%;
        border: thick $error;
        background: $surface;
        padding: 1 2;
    }

    #format-dialog .title {
        text-style: bold;
        color: $error;
        margin-bottom: 1;
    }

    #format-dialog .field-label {
        margin-top: 1;
        color: $text-muted;
    }

    #format-summary {
        margin: 1 0;
        padding: 1;
        background: $boost;
        height: auto;
        max-height: 12;
    }

    #format-log {
        margin-top: 1;
        height: 6;
        border: solid $primary-background;
        padding: 0 1;
    }

    #format-buttons {
        margin-top: 1;
        height: auto;
        align: right middle;
    }

    #format-buttons Button {
        margin-left: 1;
    }
    """

    def __init__(self, device: BlockDevice) -> None:
        super().__init__()
        self.device = device
        self._busy = False

    def compose(self) -> ComposeResult:
        fs_options = available_filesystems()
        select_options = [(fs, fs) for fs in fs_options]
        preferred = "APFS" if get_platform() == "darwin" else "ext4"
        if preferred in fs_options:
            default_fs = preferred
        elif fs_options:
            default_fs = fs_options[0]
        else:
            default_fs = Select.BLANK

        check = can_format(self.device)
        summary_lines = [
            f"Target:  {self.device.path}",
            f"Name:    {self.device.name}",
            f"Size:    {self.device.size_human}",
            f"Current: {self.device.fstype or 'none'}"
            + (f'  label="{self.device.label}"' if self.device.label else ""),
            f"Type:    {self.device.dev_type}",
        ]
        if check.reasons:
            summary_lines.append("")
            summary_lines.append("BLOCKED:")
            summary_lines.extend(f"  • {r}" for r in check.reasons)
        if check.warnings:
            summary_lines.append("")
            summary_lines.append("WARNINGS:")
            summary_lines.extend(f"  • {w}" for w in check.warnings)

        with Vertical(id="format-dialog"):
            yield Label("⚠  FORMAT DEVICE — ALL DATA WILL BE ERASED", classes="title")
            yield Static("\n".join(summary_lines), id="format-summary")
            yield Label("Filesystem", classes="field-label")
            yield Select(
                select_options,
                value=default_fs,
                id="fs-select",
                prompt="Select filesystem",
                disabled=not check.allowed or not fs_options,
            )
            yield Label("Volume label (optional)", classes="field-label")
            yield Input(
                value=self.device.label or "",
                placeholder="Label",
                id="label-input",
                disabled=not check.allowed,
            )
            yield Label(
                f'Type [bold]{self.device.name}[/bold] to confirm',
                classes="field-label",
            )
            yield Input(
                placeholder=self.device.name,
                id="confirm-input",
                disabled=not check.allowed,
            )
            yield Static("", id="format-log")
            with Horizontal(id="format-buttons"):
                yield Button("Cancel", id="btn-cancel", variant="default")
                yield Button(
                    "Format",
                    id="btn-format",
                    variant="error",
                    disabled=True,
                )

    def on_mount(self) -> None:
        check = can_format(self.device)
        if not check.allowed:
            self.query_one("#format-log", Static).update(
                f"[red]Cannot format: {check.summary}[/red]"
            )
        elif not available_filesystems():
            self.query_one("#format-log", Static).update(
                "[red]No format tools available on this platform[/red]"
            )

    @on(Input.Changed, "#confirm-input")
    def on_confirm_changed(self, event: Input.Changed) -> None:
        self._update_format_enabled()

    @on(Select.Changed, "#fs-select")
    def on_fs_changed(self, event: Select.Changed) -> None:
        self._update_format_enabled()

    def _update_format_enabled(self) -> None:
        if self._busy:
            return
        try:
            check = can_format(self.device)
            typed = self.query_one("#confirm-input", Input).value
            fs_widget = self.query_one("#fs-select", Select)
            fs_ok = fs_widget.value != Select.BLANK and bool(available_filesystems())
            btn = self.query_one("#btn-format", Button)
            btn.disabled = not (
                check.allowed and fs_ok and confirm_name_matches(self.device, typed)
            )
        except Exception:
            pass

    @on(Button.Pressed, "#btn-cancel")
    def on_cancel_pressed(self) -> None:
        self.action_cancel()

    def action_cancel(self) -> None:
        if not self._busy:
            self.dismiss(False)

    @on(Button.Pressed, "#btn-format")
    def on_format_pressed(self) -> None:
        if self._busy:
            return
        fs_value = self.query_one("#fs-select", Select).value
        label = self.query_one("#label-input", Input).value
        confirm = self.query_one("#confirm-input", Input).value
        fstype = str(fs_value) if fs_value != Select.BLANK else ""
        if not fstype or not confirm_name_matches(self.device, confirm):
            return

        self._busy = True
        self.query_one("#btn-format", Button).disabled = True
        self.query_one("#btn-cancel", Button).disabled = True
        self.query_one("#confirm-input", Input).disabled = True
        self.query_one("#label-input", Input).disabled = True
        self.query_one("#fs-select", Select).disabled = True
        self.query_one("#format-log", Static).update(
            f"[yellow]Formatting… ({privilege_hint()})[/yellow]"
        )
        self._run_format(fstype, label or None, confirm)

    @work(thread=True, exclusive=True)
    def _run_format(self, fstype: str, label: Optional[str], confirm: str) -> None:
        try:
            result = format_device(
                self.device,
                fstype,
                label=label,
                confirm_name=confirm,
            )
        except Exception as exc:  # noqa: BLE001
            result = ActionResult(False, f"Unexpected error: {exc}")

        def finish() -> None:
            self._apply_format_result(result)

        try:
            self.app.call_from_thread(finish)
        except Exception:
            # App may already be tearing down; nothing more we can do.
            pass

    def _apply_format_result(self, result: ActionResult) -> None:
        """Update UI after format finishes. Always keeps the TUI alive."""
        self._busy = False
        try:
            log = self.query_one("#format-log", Static)
        except Exception:
            # Modal already gone
            if result.ok:
                self.dismiss(True)
            return

        if result.ok:
            log.update(f"[green]{result.message}[/green]\n[dim]Closing…[/dim]")
            # Dismiss on the next tick so the green message can paint first
            self.set_timer(0.4, self._dismiss_success)
        else:
            # Keep errors visible; do not exit the app or modal until user cancels
            msg = result.message.replace("[", "\\[")
            log.update(f"[red]{msg}[/red]")
            try:
                self.query_one("#btn-cancel", Button).disabled = False
                self.query_one("#confirm-input", Input).disabled = False
                self.query_one("#label-input", Input).disabled = False
                self.query_one("#fs-select", Select).disabled = False
                self._update_format_enabled()
            except Exception:
                pass

    def _dismiss_success(self) -> None:
        if self.is_mounted:
            self.dismiss(True)

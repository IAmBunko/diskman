"""Right-click context menu for device actions."""

from __future__ import annotations

from typing import Optional

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList
from textual.widgets.option_list import Option

from diskman.models import BlockDevice
from diskman.safety import can_format, can_mount, can_unmount


class DeviceContextMenu(ModalScreen[Optional[str]]):
    """Modal action menu for a selected block device.

    Dismisses with an action id (``mount``, ``unmount``, ``format``, ``refresh``)
    or ``None`` if cancelled.
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True),
        Binding("q", "cancel", "Cancel", show=False),
    ]

    DEFAULT_CSS = """
    DeviceContextMenu {
        align: center middle;
    }

    #context-dialog {
        width: 42;
        max-width: 90%;
        height: auto;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
    }

    #context-dialog .title {
        text-style: bold;
        color: $accent;
        margin-bottom: 0;
    }

    #context-dialog .subtitle {
        color: $text-muted;
        margin-bottom: 1;
    }

    #context-options {
        height: auto;
        max-height: 12;
        border: none;
        background: transparent;
        padding: 0;
    }
    """

    def __init__(self, device: Optional[BlockDevice]) -> None:
        super().__init__()
        self.device = device

    def compose(self) -> ComposeResult:
        dev = self.device
        if dev is not None:
            title = f"{dev.name}"
            subtitle = f"{dev.size_human} · {dev.path}"
            mount_ok = can_mount(dev).allowed
            unmount_ok = can_unmount(dev).allowed
            format_ok = can_format(dev).allowed
        else:
            title = "No device"
            subtitle = "Select a device, or refresh the list"
            mount_ok = unmount_ok = format_ok = False

        options = [
            Option("Mount", id="mount", disabled=not mount_ok),
            Option("Unmount", id="unmount", disabled=not unmount_ok),
            Option("Format…", id="format", disabled=not format_ok),
            Option("Refresh", id="refresh"),
            Option("Cancel", id="cancel"),
        ]

        with Vertical(id="context-dialog"):
            yield Label(title, classes="title")
            yield Label(subtitle, classes="subtitle")
            yield OptionList(*options, id="context-options")

    def on_mount(self) -> None:
        options = self.query_one("#context-options", OptionList)
        options.focus()
        # Prefer first enabled action for keyboard convenience
        for index, option in enumerate(options.options):
            if not option.disabled and option.id not in (None, "cancel"):
                options.highlighted = index
                break

    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(OptionList.OptionSelected)
    def on_option_selected(self, event: OptionList.OptionSelected) -> None:
        action_id = event.option.id
        if action_id is None or action_id == "cancel":
            self.dismiss(None)
            return
        self.dismiss(action_id)

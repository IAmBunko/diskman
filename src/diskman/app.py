"""DiskMan Textual application."""

from __future__ import annotations

from typing import Optional

from textual import events, on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Footer, Header, Static, Tree
from textual.widgets.tree import TreeNode

from diskman.actions import mount_device, unmount_device
from diskman.discover import list_devices
from diskman.models import BlockDevice
from diskman.safety import can_format, can_mount, can_unmount
from diskman.ui.context_menu import DeviceContextMenu
from diskman.ui.detail import DetailPane
from diskman.ui.format_modal import FormatModal


class DeviceTree(Tree[str]):
    """Device tree that opens a context menu on right-click."""

    class ContextMenuRequest(Message):
        """Posted when the user right-clicks a tree row."""

        def __init__(self, node: Optional[TreeNode[str]]) -> None:
            self.node = node
            super().__init__()

    async def _on_click(self, event: events.Click) -> None:
        # Textual maps XTerm buttons as: 1=left, 2=middle, 3=right
        if event.button != 3:
            await super()._on_click(event)
            return

        meta = event.style.meta
        node: Optional[TreeNode[str]] = None
        if "line" in meta:
            line = meta["line"]
            # Select the row without treating expand/collapse glyph as toggle
            self.cursor_line = line
            await self.run_action("select_cursor")
            node = self.get_node_at_line(line)
        event.stop()
        self.post_message(self.ContextMenuRequest(node))


class DiskManApp(App[None]):
    """Terminal UI for viewing and managing block devices."""

    TITLE = "DiskMan"
    SUB_TITLE = "disk · partition · volume manager"
    CSS = """
    Screen {
        layout: vertical;
    }

    #main {
        height: 1fr;
    }

    #device-tree {
        width: 2fr;
        min-width: 30;
        border: solid $primary;
        background: $surface;
    }

    #device-tree:focus {
        border: solid $accent;
    }

    #detail-panel {
        width: 3fr;
        border: solid $primary-background;
    }

    #status-bar {
        dock: bottom;
        height: 1;
        padding: 0 1;
        background: $primary-background;
        color: $text;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("m", "mount", "Mount"),
        Binding("u", "unmount", "Unmount"),
        Binding("f", "format", "Format"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.devices: list[BlockDevice] = []
        self.selected: Optional[BlockDevice] = None
        self._node_map: dict[str, BlockDevice] = {}

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main"):
            yield DeviceTree("Block devices", id="device-tree")
            with Vertical(id="detail-panel"):
                yield DetailPane(id="detail")
        yield Static("Ready", id="status-bar")
        yield Footer()

    def on_mount(self) -> None:
        tree = self.query_one("#device-tree", DeviceTree)
        tree.show_root = False
        tree.guide_depth = 3
        self.action_refresh()

    def set_status(self, message: str) -> None:
        self.query_one("#status-bar", Static).update(message)

    def action_refresh(self) -> None:
        self._load_devices()

    def _load_devices(self) -> None:
        try:
            self.devices = list_devices()
        except Exception as exc:  # noqa: BLE001
            self.set_status(f"Error: {exc}")
            self.notify(str(exc), severity="error")
            return

        try:
            tree = self.query_one("#device-tree", Tree)
            tree.clear()
            self._node_map.clear()

            # Preserve selection by name if possible
            selected_name = self.selected.name if self.selected else None
            node_to_select: Optional[TreeNode] = None

            for disk in self.devices:
                disk_node = tree.root.add(
                    disk.tree_label(),
                    data=disk.name,
                    expand=bool(disk.children),
                )
                self._node_map[disk.name] = disk
                if selected_name == disk.name:
                    node_to_select = disk_node

                for part in disk.children:
                    part_node = disk_node.add_leaf(part.tree_label(), data=part.name)
                    self._node_map[part.name] = part
                    if selected_name == part.name:
                        node_to_select = part_node
                        disk_node.expand()

                # nested children beyond one level (rare)
                self._add_deeper(disk_node, disk)

            if node_to_select is not None:
                tree.select_node(node_to_select)
                name = node_to_select.data
                if isinstance(name, str):
                    self.selected = self._node_map.get(name)
                    self.query_one("#detail", DetailPane).show_device(self.selected)
            elif tree.root.children:
                first = tree.root.children[0]
                tree.select_node(first)
                name = first.data
                if isinstance(name, str):
                    self.selected = self._node_map.get(name)
                    self.query_one("#detail", DetailPane).show_device(self.selected)
            else:
                self.selected = None
                self.query_one("#detail", DetailPane).show_device(None)

            count = sum(len(d.walk()) for d in self.devices)
            self.set_status(
                f"Loaded {len(self.devices)} disk(s), {count} device(s) · "
                "r refresh · m mount · u unmount · f format · right-click menu · q quit"
            )
        except Exception as exc:  # noqa: BLE001
            self.set_status(f"UI refresh error: {exc}")
            self.notify(str(exc), severity="error")

    def _add_deeper(self, parent_node: TreeNode, parent_dev: BlockDevice) -> None:
        """Add grandchildren if any (usually empty for standard disks)."""
        for child in parent_dev.children:
            # children already added as leaves for partitions; only recurse if they have kids
            if not child.children:
                continue
            # Find node for this child
            child_node = None
            for n in parent_node.children:
                if n.data == child.name:
                    child_node = n
                    break
            if child_node is None:
                continue
            # Convert leaf to expandable if needed — Tree may already be leaf;
            # re-add grandchildren
            for grand in child.children:
                if grand.name not in self._node_map:
                    child_node.add_leaf(grand.tree_label(), data=grand.name)
                    self._node_map[grand.name] = grand

    @on(Tree.NodeHighlighted)
    def on_tree_highlighted(self, event: Tree.NodeHighlighted) -> None:
        data = event.node.data
        if not isinstance(data, str):
            return
        dev = self._node_map.get(data)
        self.selected = dev
        self.query_one("#detail", DetailPane).show_device(dev)
        if dev:
            self.set_status(f"Selected {dev.name} ({dev.size_human}) · {dev.path}")

    @on(Tree.NodeSelected)
    def on_tree_selected(self, event: Tree.NodeSelected) -> None:
        data = event.node.data
        if not isinstance(data, str):
            return
        dev = self._node_map.get(data)
        self.selected = dev
        self.query_one("#detail", DetailPane).show_device(dev)

    @on(DeviceTree.ContextMenuRequest)
    def on_context_menu_request(self, event: DeviceTree.ContextMenuRequest) -> None:
        """Open the right-click action menu for the node under the cursor."""
        if event.node is not None:
            data = event.node.data
            if isinstance(data, str):
                dev = self._node_map.get(data)
                self.selected = dev
                self.query_one("#detail", DetailPane).show_device(dev)
        self.push_screen(DeviceContextMenu(self.selected), self._on_context_menu_done)

    def _on_context_menu_done(self, action: Optional[str]) -> None:
        if not action:
            return
        if action == "mount":
            self.action_mount()
        elif action == "unmount":
            self.action_unmount()
        elif action == "format":
            self.action_format()
        elif action == "refresh":
            self.action_refresh()

    def action_mount(self) -> None:
        dev = self.selected
        if not dev:
            self.notify("No device selected", severity="warning")
            return
        check = can_mount(dev)
        if not check.allowed:
            self.notify(check.summary, severity="error")
            self.set_status(check.summary)
            return
        self._do_mount(dev)

    def action_unmount(self) -> None:
        dev = self.selected
        if not dev:
            self.notify("No device selected", severity="warning")
            return
        check = can_unmount(dev)
        if not check.allowed:
            self.notify(check.summary, severity="error")
            self.set_status(check.summary)
            return
        self._do_unmount(dev)

    def action_format(self) -> None:
        dev = self.selected
        if not dev:
            self.notify("No device selected", severity="warning")
            return
        check = can_format(dev)
        if not check.allowed:
            self.notify(check.summary, severity="error")
            self.set_status(check.summary)
            # Still open modal so user can see why — optional; plan says refuse
            return
        self.push_screen(FormatModal(dev), self._on_format_done)

    def _on_format_done(self, success: bool | None) -> None:
        try:
            if success:
                self.notify("Format completed", severity="information")
                self.set_status("Format completed — refreshing…")
                self.action_refresh()
            else:
                self.set_status("Format cancelled or failed")
        except Exception as exc:  # noqa: BLE001
            self.set_status(f"Post-format refresh error: {exc}")
            self.notify(str(exc), severity="error")

    @work(thread=True, exclusive=True)
    def _do_mount(self, dev: BlockDevice) -> None:
        try:
            self.app.call_from_thread(self.set_status, f"Mounting {dev.path}…")
            result = mount_device(dev)
        except Exception as exc:  # noqa: BLE001
            def err() -> None:
                self.notify(str(exc), severity="error")
                self.set_status(f"Mount error: {exc}")

            self.app.call_from_thread(err)
            return

        def done() -> None:
            try:
                if result.ok:
                    self.notify(result.message, severity="information")
                    self.set_status(result.message)
                    self.action_refresh()
                else:
                    self.notify(result.message, severity="error")
                    self.set_status(f"Mount failed: {result.message}")
            except Exception as exc:  # noqa: BLE001
                self.set_status(f"Mount UI error: {exc}")

        self.app.call_from_thread(done)

    @work(thread=True, exclusive=True)
    def _do_unmount(self, dev: BlockDevice) -> None:
        try:
            self.app.call_from_thread(self.set_status, f"Unmounting {dev.path}…")
            result = unmount_device(dev)
        except Exception as exc:  # noqa: BLE001
            def err() -> None:
                self.notify(str(exc), severity="error")
                self.set_status(f"Unmount error: {exc}")

            self.app.call_from_thread(err)
            return

        def done() -> None:
            try:
                if result.ok:
                    self.notify(result.message, severity="information")
                    self.set_status(result.message)
                    self.action_refresh()
                else:
                    self.notify(result.message, severity="error")
                    self.set_status(f"Unmount failed: {result.message}")
            except Exception as exc:  # noqa: BLE001
                self.set_status(f"Unmount UI error: {exc}")

        self.app.call_from_thread(done)


def run_app() -> None:
    DiskManApp().run()

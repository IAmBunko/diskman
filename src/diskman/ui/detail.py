"""Detail pane for the selected block device."""

from __future__ import annotations

from typing import Optional

from textual.widgets import Static

from diskman.models import BlockDevice, human_size
from diskman.safety import can_format, can_mount, can_unmount


def render_detail(dev: Optional[BlockDevice]) -> str:
    if dev is None:
        return "[dim]Select a device from the tree.[/dim]"

    rows: list[tuple[str, str]] = [
        ("Name", dev.name),
        ("Path", dev.path or "—"),
        ("Type", dev.dev_type),
        ("Size", dev.size_human),
        ("Filesystem", dev.fstype or "—"),
        ("Label", dev.label or "—"),
        ("UUID", dev.uuid or "—"),
        ("Mount", _format_mounts(dev)),
    ]

    if dev.is_disk:
        rows.extend(
            [
                ("Model", (dev.model or "—").strip()),
                ("Serial", (dev.serial or "—").strip()),
                ("Transport", dev.transport or "—"),
                ("Vendor", (dev.vendor or "—").strip()),
                ("Removable", _yn(dev.removable)),
                ("Hotplug", _yn(dev.hotplug)),
                ("Rotational", _yn(dev.rotational)),
                ("State", dev.state or "—"),
                ("Partition table", dev.pttype or "—"),
                ("Partitions", str(len(dev.children))),
            ]
        )
    else:
        rows.extend(
            [
                ("Parent", dev.pkname or "—"),
                ("Part type", dev.parttypename or dev.parttype or "—"),
                ("Part UUID", dev.partuuid or "—"),
            ]
        )
        if dev.fssize is not None or dev.fsavail is not None:
            rows.append(("FS size", human_size(dev.fssize)))
            rows.append(("FS avail", human_size(dev.fsavail)))
            rows.append(("FS use", dev.fsuse_pct or "—"))

    fmt = can_format(dev)
    mnt = can_mount(dev)
    umnt = can_unmount(dev)

    lines = ["[bold]Device details[/bold]", ""]
    width = max(len(k) for k, _ in rows)
    for key, val in rows:
        lines.append(f"[cyan]{key:<{width}}[/cyan]  {val}")

    lines.append("")
    lines.append("[bold]Actions[/bold]")
    lines.append(f"  Format   {_ok(fmt.allowed)}  {fmt.summary if not fmt.allowed else 'allowed (type-to-confirm)'}")
    lines.append(f"  Mount    {_ok(mnt.allowed)}  {mnt.summary if not mnt.allowed else 'allowed'}")
    lines.append(f"  Unmount  {_ok(umnt.allowed)}  {umnt.summary if not umnt.allowed else 'allowed'}")

    if fmt.warnings:
        lines.append("")
        lines.append("[bold yellow]Warnings[/bold yellow]")
        for w in fmt.warnings:
            lines.append(f"  • {w}")

    return "\n".join(lines)


def _format_mounts(dev: BlockDevice) -> str:
    mps = [m for m in dev.effective_mountpoints() if m]
    if not mps:
        return "—"
    if len(mps) == 1:
        return mps[0]
    # Show all if few; otherwise summarize
    if len(mps) <= 6:
        return ", ".join(mps)
    return ", ".join(mps[:5]) + f" (+{len(mps) - 5} more)"


def _yn(v: Optional[bool]) -> str:
    if v is None:
        return "—"
    return "yes" if v else "no"


def _ok(allowed: bool) -> str:
    return "[green]yes[/green]" if allowed else "[red]no[/red]"


class DetailPane(Static):
    """Rich markup detail view."""

    DEFAULT_CSS = """
    DetailPane {
        height: 1fr;
        padding: 1 2;
        overflow-y: auto;
        background: $surface;
    }
    """

    def show_device(self, dev: Optional[BlockDevice]) -> None:
        self.update(render_detail(dev))

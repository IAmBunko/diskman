# DiskMan

Terminal UI for Linux disk management: inspect physical drives, partitions, and volumes; mount/unmount; format with strong safety checks.

**Location:** `~/Applications/DiskMan`

## Features

- **Device inventory** via `lsblk` (disks, partitions, labels, UUIDs, mountpoints, transport)
- **Mount / unmount** via `udisksctl`
- **Format** via `wipefs` + `mkfs.*` with:
  - Hard blocks on system mounts (`/`, `/boot`, swap, etc.)
  - Type-to-confirm (must type the device name, e.g. `sda2`)
  - Filesystems: ext4, xfs, btrfs, f2fs, vfat, exfat (if the matching `mkfs` tool is installed)

## Requirements

- Linux with `lsblk`, `udisksctl`, `wipefs`
- Python 3.11+
- For format: `sudo` and/or `pkexec`, plus desired `mkfs.*` tools

## Run

```bash
~/Applications/DiskMan/run.sh
```

List devices without the TUI:

```bash
~/Applications/DiskMan/run.sh --list
```

Optional PATH shortcut:

```bash
ln -sf ~/Applications/DiskMan/run.sh ~/.local/bin/diskman
diskman
```

`run.sh` creates a local `.venv` and installs Textual on first run if needed.

## Keyboard & mouse

| Input | Action |
|-------|--------|
| `↑` / `↓` | Navigate device tree |
| `r` | Refresh |
| `m` | Mount selected |
| `u` | Unmount selected |
| `f` | Format wizard |
| Right-click | Context menu (Mount / Unmount / Format / Refresh) |
| `q` | Quit |

Unavailable actions in the context menu are disabled (same rules as the keyboard shortcuts). Right-click requires a terminal that forwards mouse events to the app (most modern emulators do when mouse mode is active).

## Safety

Formatting is **destructive**. DiskMan will refuse to format:

- Devices mounted at protected paths (`/`, `/boot`, `/home`, …)
- Active swap
- Virtual devices (`zram`, `loop`, …)
- Whole disks when a child partition is mounted or protected

When format is allowed, you must type the exact device basename before the Format button enables. Prefer testing on disposable USB media only.

Privilege elevation uses **non-interactive** methods only so the TUI keeps the terminal:

1. `sudo -n` (use cached credentials — run `sudo -v` in another terminal first if needed)
2. `pkexec` (desktop polkit password dialog)

Interactive `sudo` password prompts are intentionally disabled inside DiskMan; they steal stdin and would exit/corrupt the TUI.

## Project layout

```
DiskMan/
├── run.sh
├── requirements.txt
├── README.md
└── src/diskman/
    ├── app.py          # Textual app
    ├── discover.py     # lsblk inventory
    ├── safety.py       # mount/format policy
    ├── actions.py      # mount / unmount / format
    └── ui/             # detail pane, format modal
```

## Out of scope (v1)

Partition create/delete/resize, LVM/RAID, SMART dashboards, NTFS format (`mkfs.ntfs` not required).

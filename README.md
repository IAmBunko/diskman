# DiskMan

Terminal UI for disk management on **Linux** and **macOS**: inspect physical drives, partitions, and volumes; mount/unmount; format with strong safety checks.

**Location:** `~/Applications/DiskMan` (or clone from git)

## Features

- **Device inventory**
  - Linux: `lsblk` (+ `/proc/mounts`, `/proc/swaps`)
  - macOS: `diskutil list/info` (plist)
- **Mount / unmount**
  - Linux: `udisksctl`
  - macOS: `diskutil mount` / `diskutil unmount`
- **Format** with hard safety checks and type-to-confirm
  - Linux: `wipefs` + `mkfs.*` (ext4, xfs, btrfs, f2fs, vfat, exfat when tools exist)
  - macOS: `diskutil eraseVolume` / `eraseDisk` (APFS, JHFS+, ExFAT, MS-DOS FAT32, Free Space)

## Requirements

| | Linux | macOS |
|---|--------|--------|
| OS tools | `lsblk`, `udisksctl`, `wipefs`, desired `mkfs.*` | `diskutil` (built-in) |
| Python | 3.11+ | 3.11+ |
| Privilege | `sudo -n` and/or `pkexec` | `sudo -n` and/or macOS admin dialog (`osascript`) |

Windows is not supported yet (backend stub returns a clear error).

## Run

```bash
./run.sh
# or
./run.sh --list
./run.sh --version
```

Optional PATH shortcut:

```bash
ln -sf /path/to/DiskMan/run.sh ~/.local/bin/diskman
diskman
```

`run.sh` creates a local `.venv` and installs Textual on first run if needed.

### macOS notes

- Use **Terminal**, **iTerm2**, or **Ghostty** (mouse right-click works in most modern emulators).
- System volumes (`Macintosh HD`, Preboot, Recovery, VM, anything under `/System`) are blocked from format/unmount.
- Prefer testing format on a disposable USB stick.
- If elevation is needed, approve the macOS password dialog, or run `sudo -v` in another terminal first.

### Linux notes

- Install `udisks2` for mount/unmount without root in many desktop setups.
- Format elevation uses non-interactive `sudo -n` or a polkit (`pkexec`) dialog so the TUI is not corrupted by a password prompt on stdin.

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

## Safety

Formatting is **destructive**. DiskMan will refuse to format:

- Devices mounted at protected paths (`/`, `/boot`, `/System`, `/Users`, …)
- Active swap / macOS VM volumes
- Virtual devices (`zram`, `loop`, …)
- macOS system volume labels (Macintosh HD, Preboot, Recovery, …)
- Whole disks when a child partition/volume is mounted or protected

When format is allowed, you must type the exact device basename (e.g. `sda2` or `disk4s1`) before the Format button enables.

Privilege elevation uses **non-interactive** methods only so the TUI keeps the terminal:

1. Try the operation as the current user (often enough on macOS for USB media)
2. `sudo -n` (cached credentials — run `sudo -v` elsewhere if needed)
3. Desktop dialog: **pkexec** (Linux) or **osascript administrator privileges** (macOS)

## Project layout

```
DiskMan/
├── run.sh
├── requirements.txt
├── README.md
└── src/diskman/
    ├── app.py              # Textual app
    ├── discover.py         # inventory facade
    ├── actions.py          # mount/unmount/format facade
    ├── safety.py           # mount/format policy (cross-platform)
    ├── platform.py         # OS detection
    ├── models.py
    ├── backends/
    │   ├── linux.py        # lsblk / udisksctl / wipefs+mkfs
    │   ├── darwin.py       # diskutil
    │   └── unsupported.py
    └── ui/                 # detail pane, format modal, context menu
```

## Out of scope (v1)

Partition create/delete/resize, LVM/RAID, SMART dashboards, Windows backend, NTFS format on Linux (`mkfs.ntfs` not required).

"""Entry point: python -m diskman [--list]."""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="diskman",
        description="DiskMan — TUI disk manager (view, mount, format)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Print block device inventory and exit (no TUI)",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Print version and exit",
    )
    args = parser.parse_args(argv)

    if args.version:
        from diskman import __version__
        from diskman.platform import platform_label

        print(f"DiskMan {__version__} ({platform_label()})")
        return 0

    if args.list:
        from diskman.discover import format_inventory, list_devices

        try:
            devices = list_devices()
        except RuntimeError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(format_inventory(devices))
        return 0

    from diskman.app import run_app

    run_app()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
